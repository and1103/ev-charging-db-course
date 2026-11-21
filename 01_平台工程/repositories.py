"""Small parameterized repositories. Transactions belong to the calling service."""
from sqlalchemy import text


class AssetRepository:
    fields = {
        'operator': {'name'},
        'station': {'operator_id', 'name', 'address', 'longitude', 'latitude', 'spaces', 'opens', 'closes', 'parking_note', 'enabled'},
        'charger': {'station_id', 'model', 'rated_kw', 'protocol', 'warranty_until'},
        'connector': {'charger_id', 'gun_position', 'kind', 'interface', 'max_kw'},
    }

    def __init__(self, session):
        self.session = session

    def validate(self, table, values):
        if table not in self.fields or not values or set(values) - self.fields[table]:
            raise ValueError('unsupported table or fields')

    def insert(self, table, values):
        self.validate(table, values)
        columns = sorted(values)
        sql = f"INSERT INTO `{table}` ({','.join('`'+c+'`' for c in columns)}) VALUES ({','.join(':'+c for c in columns)})"
        return self.session.execute(text(sql), values).lastrowid

    def update(self, table, key, values):
        self.validate(table, values)
        sql = f"UPDATE `{table}` SET {','.join('`'+c+'`=:'+c for c in sorted(values))} WHERE id=:_key"
        return self.session.execute(text(sql), dict(values, _key=key)).rowcount

    def list(self, table, offset=0, limit=30):
        if table not in self.fields:
            raise ValueError('unsupported table')
        return [dict(x) for x in self.session.execute(
            text(f'SELECT * FROM `{table}` ORDER BY id LIMIT :limit OFFSET :offset'),
            {'limit': min(max(limit, 1), 100), 'offset': max(offset, 0)}).mappings()]

    def delete_unreferenced(self, table, key):
        if table not in self.fields:
            raise ValueError('unsupported table')
        return self.session.execute(text(f'DELETE FROM `{table}` WHERE id=:id'), {'id': key}).rowcount
