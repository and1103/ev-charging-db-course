CREATE TABLE wallet_entry (
 id bigint AUTO_INCREMENT PRIMARY KEY, account_id bigint NOT NULL, FOREIGN KEY (account_id) REFERENCES account(id),
 payment_id bigint UNIQUE, FOREIGN KEY (payment_id) REFERENCES payment(id), refund_id bigint UNIQUE, FOREIGN KEY (refund_id) REFERENCES refund(id),
 `change` numeric(12,2) NOT NULL CHECK(`change`<>0), happened_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 CHECK(((payment_id IS NOT NULL)+(refund_id IS NOT NULL))<=1)
) ENGINE=InnoDB;
CREATE TABLE redemption (
 coupon_id bigint PRIMARY KEY, FOREIGN KEY (coupon_id) REFERENCES coupon(id), order_id bigint UNIQUE NOT NULL, FOREIGN KEY (order_id) REFERENCES charge_order(id),
 discount numeric(12,2) NOT NULL CHECK(discount>0), used_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
CREATE TABLE consumer_invoice_request (
 id bigint AUTO_INCREMENT PRIMARY KEY, order_id bigint NOT NULL UNIQUE, FOREIGN KEY (order_id) REFERENCES charge_order(id),
 title varchar(255) NOT NULL, state varchar(255) NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','issued','rejected')), requested_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
CREATE TABLE driver_feedback (
 id bigint AUTO_INCREMENT PRIMARY KEY, order_id bigint NOT NULL, FOREIGN KEY (order_id) REFERENCES charge_order(id),
 kind varchar(255) NOT NULL CHECK(kind IN ('fault','rating')), content varchar(255) NOT NULL, created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

DELIMITER $$
CREATE PROCEDURE redeem_coupon(IN p_order bigint,IN p_coupon bigint,IN p_user bigint)
BEGIN
 DECLARE gross_fee decimal(12,2); DECLARE reduction decimal(12,2); DECLARE gun bigint;
 DECLARE started datetime(6); DECLARE coupon_key bigint;
 SELECT gross,connector_id,started_at INTO gross_fee,gun,started FROM charge_order
 WHERE id=p_order AND account_id=p_user AND state='billed' FOR UPDATE;
 SELECT id INTO coupon_key FROM coupon WHERE id=p_coupon AND account_id=p_user FOR UPDATE;
 SELECT LEAST(c.face,gross_fee) INTO reduction FROM campaign c JOIN coupon co ON co.campaign_id=c.id
 WHERE co.id=coupon_key AND gross_fee>=c.minimum AND NOW()>=c.starts AND NOW()<c.expires
 AND in_hours(TIME(started),c.opens,c.closes) AND (c.station_id IS NULL OR c.station_id=(SELECT station_id FROM v_gun_state WHERE id=gun));
 IF reduction IS NULL OR reduction<=0 OR EXISTS(SELECT 1 FROM payment WHERE order_id=p_order AND succeeded)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='coupon ineligible'; END IF;
 INSERT INTO redemption(coupon_id,order_id,discount) VALUES(p_coupon,p_order,reduction);
 UPDATE charge_order SET discount=reduction WHERE id=p_order;
END$$
DELIMITER ;
CREATE VIEW v_member_mask AS SELECT id,login,phone_mask,verified,tier,registered_at FROM account WHERE role='driver';
CREATE VIEW v_unused_coupon AS SELECT co.*,c.name,c.station_id,c.face,c.minimum,c.expires FROM coupon co JOIN campaign c ON c.id=co.campaign_id
 WHERE NOW()>=c.starts AND NOW()<c.expires AND NOT EXISTS(SELECT 1 FROM redemption r WHERE r.coupon_id=co.id);
CREATE VIEW v_campaign_stats AS SELECT c.id,c.name,COUNT(co.id) issued,COUNT(r.coupon_id) redeemed,COALESCE(SUM(r.discount),0) discount
 FROM campaign c LEFT JOIN coupon co ON co.campaign_id=c.id LEFT JOIN redemption r ON r.coupon_id=co.id GROUP BY c.id,c.name;
CREATE VIEW v_fleet_month AS SELECT f.fleet_id,CAST(DATE_FORMAT(o.started_at,'%Y-%m-01') AS DATE) period,COUNT(*) orders,SUM(o.gross-o.discount) amount
 FROM charge_order o JOIN fleet_card f ON f.id=o.fleet_card_id WHERE o.state IN ('billed','paid') GROUP BY 1,2;
