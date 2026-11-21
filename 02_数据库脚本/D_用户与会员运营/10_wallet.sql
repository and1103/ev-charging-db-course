-- Explicitly simulated wallet funding; no external payment provider is called.
-- topup_ref was added to wallet_entry in 05_members.sql. No COMMIT here.
DELIMITER $$
CREATE FUNCTION mock_wallet_topup(p_user bigint,p_ref varchar(255),p_amount decimal(14,4))
RETURNS bigint MODIFIES SQL DATA
main: BEGIN
 DECLARE current_balance decimal(12,2); DECLARE prior_id bigint;
 DECLARE prior_user bigint; DECLARE prior_amount decimal(12,2);
 IF p_ref IS NULL OR NOT REGEXP_LIKE(p_ref,'^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$','c')
 OR p_amount IS NULL OR p_amount<=0 OR p_amount>10000 OR p_amount<>ROUND(p_amount,2)
 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid mock topup reference or amount'; END IF;
 -- Serialize the entire wallet operation, including replay lookup and posting.
 SELECT balance INTO current_balance FROM account WHERE id=p_user AND role='driver' FOR UPDATE;
 IF current_balance IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='driver wallet not found'; END IF;
 SELECT id,account_id,`change` INTO prior_id,prior_user,prior_amount
 FROM wallet_entry WHERE topup_ref=CONVERT(p_ref USING ascii) COLLATE ascii_bin FOR UPDATE;
 IF prior_id IS NOT NULL THEN
  IF prior_user<>p_user OR prior_amount<>p_amount THEN
   SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='mock topup reference replay mismatch';
  END IF;
  RETURN prior_id;
 END IF;
 IF current_balance+p_amount>9999999999.99 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='wallet balance limit exceeded'; END IF;
 -- Insert before crediting: a concurrent different-account reference collision
 -- cannot leave a wallet credit without a unique journal entry.
 INSERT INTO wallet_entry(account_id,`change`,topup_ref) VALUES(p_user,p_amount,p_ref);
 SET prior_id=LAST_INSERT_ID();
 UPDATE account SET balance=balance+p_amount WHERE id=p_user;
 RETURN prior_id;
END$$
DELIMITER ;
