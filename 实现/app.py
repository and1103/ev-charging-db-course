import csv
from datetime import datetime, timedelta, timezone
from functools import wraps
from io import StringIO
import os

from flask import Flask, abort, g, jsonify, request, session
from flask.json.provider import DefaultJSONProvider
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from auth import password_hash, protect, verify

BEIJING = timezone(timedelta(hours=8))


class ChargeJSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(value):
        if isinstance(value, datetime):
            return value.replace(tzinfo=BEIJING).isoformat(timespec="microseconds")
        return DefaultJSONProvider.default(value)


def local_datetime(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        abort(400, "invalid ISO date/time")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(BEIJING)
    return parsed.replace(tzinfo=None)


app = Flask(__name__)
app.json = ChargeJSONProvider(app)
app.secret_key = os.environ["CHARGE_SESSION_SECRET"]
app.config.update(PERMANENT_SESSION_LIFETIME=timedelta(minutes=30), SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=2 * 1024 * 1024)
engine = create_engine(os.environ["CHARGE_DATABASE_URL"], pool_pre_ping=True, pool_size=5,
                       max_overflow=5, isolation_level="READ COMMITTED", connect_args={"init_command": "SET time_zone = '+08:00'"})
ADMIN = ("admin",)
DRIVER = ("driver",)
OPS = ("admin", "settlement")
TECH = ("admin", "maintenance")


def query(sql, **params):
    return g.db.execute(text(sql), params)


def data(*required):
    value = request.get_json()
    if not isinstance(value, dict) or any(key not in value for key in required):
        abort(400, "missing request fields")
    return value


def rows(sql, **params):
    return [dict(row) for row in query(sql, **params).mappings()]


def tx(*roles):
    def decorate(func):
        @wraps(func)
        def handler(*args, **kwargs):
            with Session(engine) as db, db.begin():
                g.db = db
                g.actor = None
                if roles:
                    if "user" not in session:
                        abort(401)
                    g.actor = query("SELECT id,role,station_id,operator_id FROM account WHERE id=:id",
                                    id=session["user"]).mappings().one_or_none()
                    if not g.actor or g.actor["role"] not in roles:
                        abort(403)
                return func(*args, **kwargs)
        return handler
    return decorate


@app.errorhandler(DBAPIError)
def database_error(error):
    code = error.orig.args[0] if error.orig.args else 0
    if code == 1644:
        return jsonify(error=str(error.orig.args[1])), 409
    if code in {1048, 1062, 1205, 1213, 1264, 1292, 1366, 1451, 1452, 3819}:
        return jsonify(error="请求违反数据约束或发生并发冲突"), 409
    app.logger.error("database error errno=%s", code)
    return jsonify(error="数据库操作失败"), 500


@app.post("/auth/register")
@tx()
def register():
    value = data("login", "password", "phone")
    if not isinstance(value["password"], str) or not 10 <= len(value["password"]) <= 128:
        abort(400, "password length must be 10–128")
    try:
        cipher, mask = protect(value["phone"], 4)
    except (TypeError, ValueError):
        abort(400, "invalid phone")
    key = query("INSERT INTO account(login,password_hash,role,phone_cipher,phone_mask)"
                " VALUES(:login,:pw,'driver',:cipher,:mask)",
                login=value["login"], pw=password_hash(value["password"]), cipher=cipher, mask=mask).lastrowid
    return {"id": key}, 201


@app.post("/auth/login")
@tx()
def login():
    value = data("login", "password")
    if not isinstance(value["password"], str) or len(value["password"]) > 128:
        abort(400)
    actor = query("SELECT *,coalesce(locked_until>now(),false) locked FROM account WHERE login=:name FOR UPDATE",
                  name=value["login"]).mappings().one_or_none()
    if not actor or actor["locked"] or not verify(value["password"], actor["password_hash"]):
        if actor and not actor["locked"]:
            query("UPDATE account SET failed_logins=CASE WHEN locked_until IS NULL THEN failed_logins+1 ELSE 1 END,"
                  " locked_until=CASE WHEN locked_until IS NULL AND failed_logins>=4 THEN NOW()+INTERVAL 15 MINUTE END WHERE id=:id",
                  id=actor["id"])
        return {"error": "登录失败或账号暂时锁定"}, 401
    query("UPDATE account SET failed_logins=0,locked_until=NULL WHERE id=:id", id=actor["id"])
    session.clear()
    session.permanent = True
    session["user"] = actor["id"]
    return {"id": actor["id"], "role": actor["role"]}


@app.post("/auth/logout")
def logout():
    session.clear()
    return "", 204


@app.get("/stations")
@tx()
def stations():
    offset = max(0, request.args.get("offset", 0, type=int))
    return rows("SELECT s.*,q.waiting FROM v_station_availability s JOIN v_queue_station q USING(id)"
                " WHERE name LIKE :name ORDER BY id LIMIT 30 OFFSET :offset",
                name="%" + request.args.get("name", "") + "%", offset=offset)


@app.get("/stations/<int:station>/guns")
@tx()
def guns(station):
    return rows("SELECT id,kind,interface,max_kw,state,ready AND (deadline IS NULL OR deadline<=now()) available"
                " FROM v_gun_state WHERE station_id=:s ORDER BY id", s=station)


@app.post("/queue")
@tx(*DRIVER)
def queue_entry():
    value = data("vehicle", "station")
    key = query("SELECT take_queue(:u,:v,:s)", u=g.actor["id"], v=value["vehicle"], s=value["station"]).scalar_one()
    query("CALL dispatch_station(:s)", s=value["station"])
    return {"id": key}, 201


@app.get("/queue")
@tx(*DRIVER)
def queue_list():
    return rows("SELECT e.*,c.connector_id,c.deadline FROM queue_entry e LEFT JOIN queue_call c ON c.id=(SELECT MAX(id) FROM queue_call WHERE entry_id=e.id)"
                " WHERE e.account_id=:u ORDER BY e.id DESC LIMIT 30", u=g.actor["id"])


@app.delete("/queue/<int:key>")
@tx(*DRIVER)
def cancel_queue(key):
    record = query("UPDATE queue_entry SET state='cancelled' WHERE id=:id AND account_id=:u "
                   "AND state IN ('waiting','called')", id=key, u=g.actor["id"]).rowcount
    if record == 0:
        abort(404)
    # The scheduler releases the gun after this transaction, preserving the gun → queue lock order.
    return "", 204


@app.post("/estimate")
@tx(*DRIVER)
def estimate():
    value = data("vehicle", "gun", "at", "current_soc", "target_soc")
    result = rows("SELECT t.id tariff_id,e.kwh,greatest(0,e.kwh/e.kw*60) minutes,"
                  " estimate_charge(t.id,CAST(:at AS DATETIME(6)),e.kwh,e.kw) amount FROM vehicle v"
                  " JOIN vehicle_binding b ON b.vehicle_id=v.id AND b.binding_end IS NULL AND b.account_id=:u"
                  " JOIN v_gun_state g ON g.id=:gun AND compatible(v.id,g.id)"
                  " JOIN tariff t ON t.station_id=g.station_id AND t.fleet_id IS NULL"
                  " AND CAST(:at AS DATETIME(6))>=t.starts AND CAST(:at AS DATETIME(6))<t.ends"
                  " JOIN LATERAL (SELECT v.capacity_kwh*(CAST(:target AS DECIMAL(8,3))-CAST(:current AS DECIMAL(8,3)))/100 kwh,"
                  " least(v.max_kw,g.max_kw) kw) e ON true WHERE v.id=:v AND CAST(:current AS DECIMAL(8,3))>=0"
                  " AND CAST(:target AS DECIMAL(8,3))<=100 AND e.kwh>0",
                  u=g.actor["id"], gun=value["gun"], v=value["vehicle"], at=local_datetime(value["at"]),
                  current=value["current_soc"], target=value["target_soc"])
    if not result or result[0]["amount"] is None:
        abort(409, "no compatible tariff or invalid SOC")
    return result[0]


@app.post("/orders")
@tx(*DRIVER)
def open_order():
    value = data("vehicle", "gun")
    key = query("SELECT open_charge(:u,:v,:g,:card)", u=g.actor["id"], v=value["vehicle"],
                g=value["gun"], card=value.get("card")).scalar_one()
    return {"id": key}, 201


@app.get("/orders")
@tx(*DRIVER, *OPS)
def orders():
    return rows("SELECT * FROM v_order_balance WHERE (:staff OR account_id=:u) ORDER BY id DESC LIMIT 30 OFFSET :off",
                staff=g.actor["role"] in OPS, u=g.actor["id"], off=max(0, request.args.get("offset", 0, type=int)))


@app.get("/orders/<int:key>")
@tx(*DRIVER, *OPS)
def order(key):
    result = rows("SELECT * FROM v_order_balance WHERE id=:id AND (:staff OR account_id=:u)",
                  id=key, staff=g.actor["role"] in OPS, u=g.actor["id"])
    if not result:
        abort(404)
    return {"order": result[0], "segments": rows("SELECT * FROM fee_detail WHERE order_id=:id ORDER BY begins", id=key),
            "payments": rows("SELECT * FROM payment WHERE order_id=:id ORDER BY id", id=key)}


@app.post("/orders/<int:key>/coupon")
@tx(*DRIVER)
def coupon(key):
    query("CALL redeem_coupon(:o,:c,:u)", o=key, c=data("coupon")["coupon"], u=g.actor["id"])
    query("UPDATE charge_order SET state='paid' WHERE id=:id AND state='billed' AND gross=discount", id=key)
    return "", 204


@app.post("/orders/<int:key>/pay")
@tx(*DRIVER)
def pay(key):
    value = data("reference", "amount")
    key = query("SELECT post_payment(:u,:o,:c,:r,:m,true)", u=g.actor["id"], o=key, c=value.get("channel", "mock"),
                r=value["reference"], m=value["amount"]).scalar_one()
    return {"payment_id": key}


@app.post("/demo/order/<int:key>/readings")
@tx(*ADMIN)
def readings(key):
    samples = data("samples")["samples"]
    if not isinstance(samples, list) or not 1 <= len(samples) <= 1000:
        abort(400)
    if not query("SELECT 1 FROM charge_order WHERE id=:id AND state='charging' FOR UPDATE", id=key).scalar():
        abort(409)
    g.db.execute(text("INSERT INTO meter_sample VALUES(:order_id,:at,:reading)"),
                 [{"order_id": key, "at": local_datetime(item["at"]), "reading": item["reading"]} for item in samples])
    return "", 204


@app.post("/demo/order/<int:key>/finish")
@tx(*ADMIN)
def finish(key):
    value = data("at")
    query("CALL finish_charge(:id,:at,:disconnect)", id=key, at=local_datetime(value["at"]), disconnect=value.get("disconnect", False))
    return "", 204


@app.post("/orders/<int:key>/review")
@tx(*OPS)
def review(key):
    value = data("adjustment", "conclusion")
    query("CALL approve_review(:id,:u,:amount,:note)", id=key, u=g.actor["id"],
          amount=value["adjustment"], note=value["conclusion"])
    return "", 204


@app.post("/payments/<int:key>/refund")
@tx(*OPS)
def refund(key):
    value = data("reference", "amount")
    return {"id": query("SELECT post_refund(:p,:r,:m)", p=key, r=value["reference"], m=value["amount"]).scalar_one()}


@app.post("/demo/chargers/<int:key>/state")
@tx(*ADMIN)
def device_state(key):
    query("CALL process_charger(:id,:state)", id=key, state=data("state")["state"])
    return "", 204


@app.post("/demo/chargers/<int:key>/telemetry")
@tx(*ADMIN)
def telemetry(key):
    value = data("samples")["samples"]
    if not isinstance(value, list) or not 1 <= len(value) <= 1000:
        abort(400)
    columns = ("at", "volts", "amps", "kw", "temperature", "offline_seconds", "fault_code")
    payload = [dict(charger=key, **{column: local_datetime(row.get(column)) if column == "at" else row.get(column) for column in columns}) for row in value]
    g.db.execute(text("INSERT INTO telemetry VALUES(:charger,:at,:volts,:amps,:kw,:temperature,:offline_seconds,:fault_code)"), payload)
    for code in {row["fault_code"] for row in payload if row["fault_code"]}:
        query("SELECT raise_alarm(:id,:code)", id=key, code=code)
    return "", 204


@app.get("/alarms")
@tx(*TECH)
def alarms():
    return rows("SELECT * FROM v_live_alarm WHERE (:admin OR station_id=:s) ORDER BY deadline LIMIT 100",
                admin=g.actor["role"] == "admin", s=g.actor["station_id"])


@app.post("/alarms/<int:key>/assign")
@tx(*ADMIN)
def assign_work(key):
    technician = data("technician")["technician"]
    result = query("INSERT INTO work_order(alarm_id,technician_id)"
                   " SELECT a.id,u.id FROM v_live_alarm a JOIN account u ON u.station_id=a.station_id"
                   " WHERE a.id=:id AND u.id=:u AND u.role='maintenance'", id=key, u=technician)
    if not result.rowcount:
        abort(409, "invalid station technician or alarm")
    return {"id": result.lastrowid}, 201


@app.post("/work/<int:key>/step")
@tx(*TECH)
def work_step(key):
    value = data("step")
    columns = {"accept": "accepted_at", "arrive": "arrived_at", "repair": "repaired_at", "close": "closed_at"}
    column = columns.get(value["step"])
    if not column:
        abort(400)
    result = query(f"UPDATE work_order SET {column}=SYSDATE(6),result=coalesce(:note,result)"
                   " WHERE id=:id AND (:admin OR technician_id=:u)"
                   f" AND {column} IS NULL", note=value.get("result"), id=key,
                   admin=g.actor["role"] == "admin", u=g.actor["id"]).rowcount
    if result == 0:
        abort(404)
    return "", 204


@app.post("/alarms/<int:key>/recover")
@tx(*ADMIN)
def recover(key):
    query("CALL recover_alarm(:id)", id=key)
    return "", 204


@app.post("/admin/tick")
@tx(*ADMIN)
def tick():
    query("CALL scan_offline()")
    query("CALL escalate_alarms(SYSDATE(6))")
    for station in rows("SELECT id FROM station ORDER BY id"):
        query("CALL dispatch_station(:id)", id=station["id"])
    return "", 204


@app.post("/vehicles")
@tx(*DRIVER)
def vehicle():
    value = data("plate", "model", "capacity_kwh", "max_kw", "supports_dc", "interface")
    try:
        cipher, mask = protect(value["plate"], 3)
    except (ValueError, TypeError):
        abort(400)
    key = query("INSERT INTO vehicle(plate_cipher,plate_mask,model,capacity_kwh,max_kw,supports_dc,interface)"
                " VALUES(:cipher,:mask,:model,:capacity_kwh,:max_kw,:supports_dc,:interface)",
                **{k: value[k] for k in ("model", "capacity_kwh", "max_kw", "supports_dc", "interface")}, cipher=cipher, mask=mask).lastrowid
    query("INSERT INTO vehicle_binding(vehicle_id,account_id) VALUES(:id,:u)", id=key, u=g.actor["id"])
    return {"id": key}, 201


@app.get("/me")
@tx(*DRIVER)
def me():
    key = g.actor["id"]
    return {"account": rows("SELECT id,login,phone_mask,balance,tier,verified FROM account WHERE id=:u", u=key)[0],
            "vehicles": rows("SELECT v.id,v.plate_mask,v.model FROM vehicle v JOIN vehicle_binding b ON b.vehicle_id=v.id"
                             " WHERE b.account_id=:u AND b.binding_end IS NULL", u=key),
            "coupons": rows("SELECT * FROM v_unused_coupon WHERE account_id=:u", u=key),
            "wallet": rows("SELECT * FROM wallet_entry WHERE account_id=:u ORDER BY id DESC LIMIT 30", u=key)}


@app.post("/campaigns/<int:key>/claim")
@tx(*DRIVER)
def claim(key):
    return {"id": query("SELECT issue_coupon(:c,:u)", c=key, u=g.actor["id"]).scalar_one()}


@app.get("/settlements")
@tx(*OPS, "operator")
def settlements():
    return rows("SELECT * FROM v_invoice_balance WHERE (:staff OR operator_id=:operator) ORDER BY period DESC,id LIMIT 100",
                staff=g.actor["role"] in OPS, operator=g.actor["operator_id"])


@app.post("/settlements")
@tx(*OPS)
def build():
    value = data("station", "period")
    query("CALL build_settlement(:s,CAST(:p AS date))", s=value["station"], p=value["period"])
    return "", 204


@app.get("/settlements/<int:key>")
@tx(*OPS, "operator")
def settlement(key):
    result = rows("SELECT * FROM v_invoice_balance WHERE id=:id AND (:staff OR operator_id=:operator)",
                  id=key, staff=g.actor["role"] in OPS, operator=g.actor["operator_id"])
    if not result:
        abort(404)
    return {"settlement": result[0], "differences": rows(
        "SELECT d.*,(SELECT GROUP_CONCAT(side ORDER BY side) FROM diff_confirmation c WHERE c.diff_id=d.id) confirmed_by"
        " FROM recon_diff d WHERE settlement_id=:id ORDER BY id", id=key),
        "invoices": rows("SELECT * FROM settlement_invoice WHERE settlement_id=:id ORDER BY id", id=key)}


@app.post("/settlements/<int:key>/import")
@tx(*OPS)
def import_bill(key):
    try:
        reader = csv.DictReader(StringIO(request.get_data(as_text=True)))
        imported = list(reader)
        if not 1 <= len(imported) <= 10000 or not {"order_id", "kwh", "amount", "paid"}.issubset(reader.fieldnames or ()):
            abort(400, "invalid CSV columns")
        for row in imported:
            if row["paid"] not in {"true", "false"}:
                abort(400, "paid must be true or false")
            result = query("INSERT INTO external_bill(settlement_id,order_id,batch,kwh,amount,paid)"
                           " SELECT :s,order_id,:batch,:kwh,:amount,:paid FROM settlement_item"
                           " WHERE settlement_id=:s AND order_id=:order_id ",
                           s=key, batch=request.args.get("batch", "local"), order_id=int(row["order_id"]),
                           kwh=row["kwh"], amount=row["amount"], paid=row["paid"] == "true").rowcount
            if result == 0:
                abort(409, "order missing from draft or already imported")
    except (TypeError, ValueError):
        abort(400, "invalid CSV values")
    query("CALL compare_settlement(:id)", id=key)
    return "", 204


@app.post("/differences/<int:key>/confirm")
@tx(*OPS, "operator")
def confirm_diff(key):
    conclusion = data("conclusion")["conclusion"]
    if conclusion not in {"accept", "reject"}:
        abort(400)
    query("CALL confirm_difference(:d,:u,:note)", d=key, u=g.actor["id"], note=conclusion)
    return "", 204


@app.post("/settlements/<int:key>/confirm")
@tx(*OPS)
def confirm_bill(key):
    query("CALL confirm_settlement(:id)", id=key)
    return "", 204


@app.post("/settlements/<int:key>/invoice")
@tx(*OPS)
def invoice(key):
    value = data("title", "tax_id", "amount")
    result = query("INSERT INTO settlement_invoice(settlement_id,title,tax_id,amount,original_id)"
                   " VALUES(:id,:t,:tax,:a,:origin)", id=key, t=value["title"], tax=value["tax_id"],
                   a=value["amount"], origin=value.get("original")).lastrowid
    return {"id": result}, 201


@app.post("/admin/users/<int:key>/verify")
@tx(*ADMIN)
def verify_user(key):
    if not query("UPDATE account SET verified=true WHERE id=:id AND role='driver'", id=key).rowcount:
        abort(404)
    return "", 204


@app.post("/admin/chargers/<int:key>/commission")
@tx(*ADMIN)
def commission(key):
    query("CALL commission_charger(:id,:r)", id=key, r=data("request")["request"])
    return "", 204


@app.get("/admin/stations/<int:key>/assets")
@tx(*TECH)
def assets(key):
    if g.actor["role"] == "maintenance" and g.actor["station_id"] != key:
        abort(403)
    return {"chargers": rows("SELECT * FROM charger WHERE station_id=:s ORDER BY id", s=key),
            "guns": rows("SELECT * FROM v_gun_state WHERE station_id=:s ORDER BY id", s=key),
            "history": rows("SELECT * FROM v_asset_history WHERE station_id=:s ORDER BY id DESC LIMIT 30", s=key)}


@app.post("/orders/<int:key>/invoice-request")
@tx(*DRIVER)
def consumer_invoice(key):
    result = query("INSERT INTO consumer_invoice_request(order_id,title)"
                   " SELECT id,:title FROM charge_order WHERE id=:id AND account_id=:u AND state='paid'",
                   title=data("title")["title"], id=key, u=g.actor["id"])
    if not result.rowcount:
        abort(404)
    return {"id": result.lastrowid}, 201


@app.post("/orders/<int:key>/feedback")
@tx(*DRIVER)
def feedback(key):
    value = data("kind", "content")
    result = query("INSERT INTO driver_feedback(order_id,kind,content)"
                   " SELECT id,:kind,:content FROM charge_order WHERE id=:id AND account_id=:u",
                   kind=value["kind"], content=value["content"], id=key, u=g.actor["id"])
    if not result.rowcount:
        abort(404)
    return {"id": result.lastrowid}, 201


@app.get("/fleets/<int:key>/months")
@tx("fleet", *ADMIN)
def fleet_months(key):
    return rows("SELECT v.* FROM v_fleet_month v JOIN fleet f ON f.id=v.fleet_id"
                " WHERE f.id=:id AND (:admin OR f.manager_id=:u) ORDER BY v.period DESC LIMIT 24",
                id=key, u=g.actor["id"], admin=g.actor["role"] == "admin")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
