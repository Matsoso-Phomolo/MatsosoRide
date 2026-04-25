-- ═══════════════════════════════════════════════════════════════════
-- URBAN CAB — MySQL Schema (v4.0)
-- Maseru CBD + MSU Local Passenger Transportation System
-- Includes: Tables · Triggers · Views · Stored Procedures
--
-- HOW TO USE:
--   mysql -u root -p < urban_cab_mysql.sql
--   OR open in MySQL Workbench → run the whole script.
-- ═══════════════════════════════════════════════════════════════════

DROP DATABASE IF EXISTS lipalangoang;
CREATE DATABASE lipalangoang
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE lipalangoang;

-- ───────────────────────────────────────────────────────────────────
--  SECTION 1 — TABLES
-- ───────────────────────────────────────────────────────────────────

CREATE TABLE Locations (
  location_id   INT          NOT NULL AUTO_INCREMENT,
  location_name VARCHAR(120) NOT NULL,
  area_zone     VARCHAR(40)  NOT NULL DEFAULT 'CBD',
  description   VARCHAR(255)          DEFAULT NULL,
  is_active     TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (location_id),
  UNIQUE KEY uq_location_name (location_name),
  INDEX idx_loc_zone (area_zone)
) ENGINE=InnoDB;

CREATE TABLE Payment_Methods (
  payment_method_id INT         NOT NULL AUTO_INCREMENT,
  method_name       VARCHAR(60) NOT NULL,
  description       VARCHAR(255)         DEFAULT NULL,
  is_active         TINYINT(1)  NOT NULL DEFAULT 1,
  PRIMARY KEY (payment_method_id),
  UNIQUE KEY uq_method_name (method_name)
) ENGINE=InnoDB;

-- Fixed rate table: zone_from x zone_to -> amount (Maloti)
CREATE TABLE Fares (
  fare_id   INT          NOT NULL AUTO_INCREMENT,
  zone_from VARCHAR(40)  NOT NULL,
  zone_to   VARCHAR(40)  NOT NULL,
  amount    DECIMAL(8,2) NOT NULL,
  PRIMARY KEY (fare_id),
  UNIQUE KEY uq_zone_pair (zone_from, zone_to)
) ENGINE=InnoDB;

CREATE TABLE Drivers (
  driver_id      INT          NOT NULL AUTO_INCREMENT,
  first_name     VARCHAR(60)  NOT NULL,
  last_name      VARCHAR(60)  NOT NULL,
  phone_number   VARCHAR(20)  NOT NULL,
  license_number VARCHAR(30)  NOT NULL,
  vehicle_plate  VARCHAR(15)  NOT NULL,
  vehicle_model  VARCHAR(80)           DEFAULT NULL,
  password_hash  VARCHAR(64)  NOT NULL,
  is_available   TINYINT(1)   NOT NULL DEFAULT 0,
  joined_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (driver_id),
  UNIQUE KEY uq_driver_phone   (phone_number),
  UNIQUE KEY uq_driver_license (license_number),
  UNIQUE KEY uq_driver_plate   (vehicle_plate)
) ENGINE=InnoDB;

CREATE TABLE Admin_Users (
  admin_id      INT         NOT NULL AUTO_INCREMENT,
  username      VARCHAR(40) NOT NULL,
  email         VARCHAR(120)NOT NULL,
  password_hash VARCHAR(64) NOT NULL,
  role          VARCHAR(20) NOT NULL DEFAULT 'admin',
  created_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (admin_id),
  UNIQUE KEY uq_admin_username (username),
  UNIQUE KEY uq_admin_email    (email)
) ENGINE=InnoDB;

-- Core transaction table — passenger identity stored inline
CREATE TABLE Rides (
  ride_id             INT          NOT NULL AUTO_INCREMENT,
  passenger_name      VARCHAR(120) NOT NULL,
  passenger_phone     VARCHAR(20)  NOT NULL,
  pickup_location_id  INT          NOT NULL,
  dropoff_location_id INT          NOT NULL,
  driver_id           INT                   DEFAULT NULL,
  payment_method_id   INT          NOT NULL,
  ride_status         VARCHAR(20)  NOT NULL DEFAULT 'REQUESTED',
  requested_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  accepted_at         DATETIME              DEFAULT NULL,
  completed_at        DATETIME              DEFAULT NULL,
  fare_amount         DECIMAL(8,2)          DEFAULT NULL,
  notes               TEXT                  DEFAULT NULL,
  PRIMARY KEY (ride_id),
  CONSTRAINT chk_different_locations
    CHECK (pickup_location_id <> dropoff_location_id),
  CONSTRAINT chk_ride_status
    CHECK (ride_status IN
      ('REQUESTED','ACCEPTED','IN_PROGRESS','COMPLETED','CANCELLED')),
  FOREIGN KEY fk_ride_pickup  (pickup_location_id)
    REFERENCES Locations(location_id),
  FOREIGN KEY fk_ride_dropoff (dropoff_location_id)
    REFERENCES Locations(location_id),
  FOREIGN KEY fk_ride_driver  (driver_id)
    REFERENCES Drivers(driver_id),
  FOREIGN KEY fk_ride_payment (payment_method_id)
    REFERENCES Payment_Methods(payment_method_id),
  INDEX idx_ride_status    (ride_status),
  INDEX idx_ride_driver    (driver_id),
  INDEX idx_ride_requested (requested_at),
  INDEX idx_ride_phone     (passenger_phone)
) ENGINE=InnoDB;

-- Audit log of driver availability and location changes
CREATE TABLE Vehicle_Status (
  status_id           INT         NOT NULL AUTO_INCREMENT,
  driver_id           INT         NOT NULL,
  status              VARCHAR(20) NOT NULL DEFAULT 'OFFLINE',
  current_location_id INT                  DEFAULT NULL,
  updated_at          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                           ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (status_id),
  CONSTRAINT chk_vs_status
    CHECK (status IN ('AVAILABLE','ON_RIDE','OFFLINE')),
  FOREIGN KEY fk_vs_driver   (driver_id)
    REFERENCES Drivers(driver_id),
  FOREIGN KEY fk_vs_location (current_location_id)
    REFERENCES Locations(location_id),
  INDEX idx_vs_driver (driver_id)
) ENGINE=InnoDB;

-- Materialised management summaries (intentional denormalisation)
CREATE TABLE Ride_Reports (
  report_id       INT           NOT NULL AUTO_INCREMENT,
  admin_id        INT           NOT NULL,
  report_type     VARCHAR(60)   NOT NULL DEFAULT 'Daily Summary',
  report_date     DATE          NOT NULL,
  total_rides     INT           NOT NULL DEFAULT 0,
  total_revenue   DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  top_location_id INT                    DEFAULT NULL,
  generated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  notes           TEXT                   DEFAULT NULL,
  PRIMARY KEY (report_id),
  FOREIGN KEY fk_rr_admin    (admin_id)
    REFERENCES Admin_Users(admin_id),
  FOREIGN KEY fk_rr_location (top_location_id)
    REFERENCES Locations(location_id),
  INDEX idx_rr_date (report_date)
) ENGINE=InnoDB;


-- ───────────────────────────────────────────────────────────────────
--  SECTION 2 — TRIGGERS
--  Business rules enforced at the database level, independent of
--  which application, script, or tool touches the data.
-- ───────────────────────────────────────────────────────────────────

DELIMITER $$

-- Trigger 1: Ride accepted -> mark driver unavailable, log to Vehicle_Status
CREATE TRIGGER trg_ride_accepted
AFTER UPDATE ON Rides
FOR EACH ROW
BEGIN
  IF NEW.ride_status = 'ACCEPTED' AND OLD.ride_status = 'REQUESTED' THEN
    UPDATE Drivers SET is_available = 0 WHERE driver_id = NEW.driver_id;
    INSERT INTO Vehicle_Status (driver_id, status)
    VALUES (NEW.driver_id, 'ON_RIDE');
  END IF;
END$$

-- Trigger 2: Ride completed or cancelled -> free the driver, log to Vehicle_Status
CREATE TRIGGER trg_ride_closed
AFTER UPDATE ON Rides
FOR EACH ROW
BEGIN
  IF NEW.ride_status = 'COMPLETED' AND OLD.ride_status = 'IN_PROGRESS' THEN
    UPDATE Drivers SET is_available = 1 WHERE driver_id = NEW.driver_id;
    INSERT INTO Vehicle_Status (driver_id, status) VALUES (NEW.driver_id, 'AVAILABLE');
  END IF;
  IF NEW.ride_status = 'CANCELLED'
     AND OLD.ride_status IN ('ACCEPTED','IN_PROGRESS')
     AND NEW.driver_id IS NOT NULL THEN
    UPDATE Drivers SET is_available = 1 WHERE driver_id = NEW.driver_id;
    INSERT INTO Vehicle_Status (driver_id, status) VALUES (NEW.driver_id, 'AVAILABLE');
  END IF;
END$$

-- Trigger 3: Guard against invalid status transitions
CREATE TRIGGER trg_ride_status_guard
BEFORE UPDATE ON Rides
FOR EACH ROW
BEGIN
  DECLARE allowed INT DEFAULT 0;
  IF OLD.ride_status = 'REQUESTED'   AND NEW.ride_status IN ('ACCEPTED','CANCELLED')    THEN SET allowed = 1; END IF;
  IF OLD.ride_status = 'ACCEPTED'    AND NEW.ride_status IN ('IN_PROGRESS','CANCELLED') THEN SET allowed = 1; END IF;
  IF OLD.ride_status = 'IN_PROGRESS' AND NEW.ride_status IN ('COMPLETED','CANCELLED')   THEN SET allowed = 1; END IF;
  IF OLD.ride_status = NEW.ride_status THEN SET allowed = 1; END IF;
  IF OLD.ride_status IN ('COMPLETED','CANCELLED') AND NEW.ride_status != OLD.ride_status THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Completed or cancelled rides cannot change status.';
  END IF;
  IF allowed = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Invalid ride status transition.';
  END IF;
END$$

-- Trigger 4: Auto-set fare on INSERT if app did not provide one
CREATE TRIGGER trg_ride_set_fare
BEFORE INSERT ON Rides
FOR EACH ROW
BEGIN
  DECLARE v_fare DECIMAL(8,2) DEFAULT NULL;
  IF NEW.fare_amount IS NULL THEN
    SELECT f.amount INTO v_fare
    FROM   Fares f
    JOIN   Locations pu ON pu.area_zone = f.zone_from
    JOIN   Locations dr ON dr.area_zone = f.zone_to
    WHERE  pu.location_id = NEW.pickup_location_id
    AND    dr.location_id = NEW.dropoff_location_id
    LIMIT  1;
    SET NEW.fare_amount = v_fare;
  END IF;
END$$

DELIMITER ;


-- ───────────────────────────────────────────────────────────────────
--  SECTION 3 — VIEWS
--  Pre-joined queries used repeatedly by the application.
--  The app selects from views instead of writing the same 5-table
--  JOIN every time.
-- ───────────────────────────────────────────────────────────────────

-- View 1: Full ride details — all FKs resolved to readable names
CREATE VIEW vw_rides_full AS
SELECT
  r.ride_id,
  r.passenger_name,
  r.passenger_phone,
  r.ride_status,
  r.requested_at,
  r.accepted_at,
  r.completed_at,
  r.fare_amount,
  r.notes,
  r.pickup_location_id,
  pu.location_name AS pickup_name,
  pu.area_zone     AS pickup_zone,
  r.dropoff_location_id,
  dr.location_name AS dropoff_name,
  dr.area_zone     AS dropoff_zone,
  r.driver_id,
  CONCAT(d.first_name,' ',d.last_name) AS driver_name,
  d.vehicle_plate,
  d.vehicle_model,
  d.phone_number   AS driver_phone,
  r.payment_method_id,
  pm.method_name
FROM       Rides         r
JOIN       Locations     pu ON r.pickup_location_id  = pu.location_id
JOIN       Locations     dr ON r.dropoff_location_id = dr.location_id
JOIN       Payment_Methods pm ON r.payment_method_id = pm.payment_method_id
LEFT JOIN  Drivers        d  ON r.driver_id          = d.driver_id;

-- View 2: Driver stats — total rides and earnings per driver
CREATE VIEW vw_driver_stats AS
SELECT
  d.driver_id,
  d.first_name,
  d.last_name,
  CONCAT(d.first_name,' ',d.last_name) AS full_name,
  d.phone_number,
  d.license_number,
  d.vehicle_plate,
  d.vehicle_model,
  d.is_available,
  d.joined_at,
  COUNT(r.ride_id)                AS total_rides,
  COALESCE(SUM(r.fare_amount),0)  AS total_earned,
  COALESCE(AVG(r.fare_amount),0)  AS avg_fare,
  SUM(CASE WHEN r.ride_status='COMPLETED' THEN 1 ELSE 0 END) AS completed_rides,
  SUM(CASE WHEN r.ride_status='CANCELLED' THEN 1 ELSE 0 END) AS cancelled_rides
FROM      Drivers d
LEFT JOIN Rides   r ON d.driver_id = r.driver_id AND r.ride_status = 'COMPLETED'
GROUP BY  d.driver_id, d.first_name, d.last_name,
          d.phone_number, d.license_number, d.vehicle_plate,
          d.vehicle_model, d.is_available, d.joined_at;

-- View 3: Location demand — ride count per location
CREATE VIEW vw_location_demand AS
SELECT
  l.location_id,
  l.location_name,
  l.area_zone,
  l.is_active,
  COUNT(r.ride_id) AS total_rides,
  SUM(CASE WHEN r.pickup_location_id  = l.location_id THEN 1 ELSE 0 END) AS pickup_count,
  SUM(CASE WHEN r.dropoff_location_id = l.location_id THEN 1 ELSE 0 END) AS dropoff_count
FROM      Locations l
LEFT JOIN Rides     r ON l.location_id IN (r.pickup_location_id, r.dropoff_location_id)
GROUP BY  l.location_id, l.location_name, l.area_zone, l.is_active;

-- View 4: Daily revenue summary for the reports chart
CREATE VIEW vw_daily_revenue AS
SELECT
  DATE(requested_at)  AS ride_date,
  COUNT(*)            AS total_rides,
  SUM(CASE WHEN ride_status='COMPLETED' THEN 1    ELSE 0    END) AS completed_rides,
  COALESCE(SUM(CASE WHEN ride_status='COMPLETED'
                    THEN fare_amount ELSE 0 END), 0)             AS revenue
FROM  Rides
GROUP BY DATE(requested_at);

-- View 5: Pending rides — waiting for a driver (driver dashboard)
CREATE VIEW vw_pending_rides AS
SELECT
  r.ride_id,
  r.passenger_name,
  r.passenger_phone,
  r.requested_at,
  r.fare_amount,
  r.notes,
  pu.location_name  AS pickup_name,
  pu.area_zone      AS pickup_zone,
  dr.location_name  AS dropoff_name,
  dr.area_zone      AS dropoff_zone,
  pm.method_name
FROM  Rides           r
JOIN  Locations       pu ON r.pickup_location_id  = pu.location_id
JOIN  Locations       dr ON r.dropoff_location_id = dr.location_id
JOIN  Payment_Methods pm ON r.payment_method_id   = pm.payment_method_id
WHERE r.ride_status = 'REQUESTED'
AND   r.driver_id   IS NULL
ORDER BY r.requested_at ASC;


-- ───────────────────────────────────────────────────────────────────
--  SECTION 4 — STORED PROCEDURES
--  Each multi-step operation is a procedure with START TRANSACTION /
--  COMMIT / ROLLBACK so it either fully succeeds or fully fails.
-- ───────────────────────────────────────────────────────────────────

DELIMITER $$

-- sp_accept_ride: assign driver, set ACCEPTED. Uses SELECT ... FOR UPDATE
-- to prevent two drivers accepting the same ride simultaneously.
CREATE PROCEDURE sp_accept_ride(
  IN  p_ride_id   INT,
  IN  p_driver_id INT,
  OUT p_success   TINYINT,
  OUT p_message   VARCHAR(200)
)
BEGIN
  DECLARE v_status         VARCHAR(20);
  DECLARE v_current_driver INT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    SET p_success = 0;
    SET p_message = 'Database error — ride could not be accepted.';
  END;

  START TRANSACTION;

  SELECT ride_status, driver_id
  INTO   v_status, v_current_driver
  FROM   Rides WHERE ride_id = p_ride_id
  FOR UPDATE;

  IF v_status != 'REQUESTED' OR v_current_driver IS NOT NULL THEN
    ROLLBACK;
    SET p_success = 0;
    SET p_message = 'Ride is no longer available.';
  ELSE
    UPDATE Rides
    SET    driver_id = p_driver_id, ride_status = 'ACCEPTED', accepted_at = NOW()
    WHERE  ride_id   = p_ride_id;
    COMMIT;
    SET p_success = 1;
    SET p_message = 'Ride accepted successfully.';
  END IF;
END$$

-- sp_start_ride: ACCEPTED -> IN_PROGRESS
CREATE PROCEDURE sp_start_ride(
  IN  p_ride_id   INT,
  IN  p_driver_id INT,
  OUT p_success   TINYINT,
  OUT p_message   VARCHAR(200)
)
BEGIN
  DECLARE v_rows INT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    SET p_success = 0;
    SET p_message = 'Database error — ride could not be started.';
  END;

  START TRANSACTION;
  UPDATE Rides SET ride_status = 'IN_PROGRESS'
  WHERE  ride_id = p_ride_id AND driver_id = p_driver_id AND ride_status = 'ACCEPTED';
  SET v_rows = ROW_COUNT();

  IF v_rows = 0 THEN
    ROLLBACK;
    SET p_success = 0;
    SET p_message = 'Ride not found or not in ACCEPTED state.';
  ELSE
    COMMIT;
    SET p_success = 1;
    SET p_message = 'Ride started.';
  END IF;
END$$

-- sp_complete_ride: IN_PROGRESS -> COMPLETED
-- Trigger trg_ride_closed handles driver availability automatically.
CREATE PROCEDURE sp_complete_ride(
  IN  p_ride_id   INT,
  IN  p_driver_id INT,
  OUT p_success   TINYINT,
  OUT p_message   VARCHAR(200),
  OUT p_fare      DECIMAL(8,2)
)
BEGIN
  DECLARE v_status VARCHAR(20);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    SET p_success = 0;
    SET p_message = 'Database error — ride could not be completed.';
  END;

  START TRANSACTION;

  SELECT ride_status, fare_amount INTO v_status, p_fare
  FROM   Rides WHERE ride_id = p_ride_id AND driver_id = p_driver_id
  FOR UPDATE;

  IF v_status != 'IN_PROGRESS' THEN
    ROLLBACK;
    SET p_success = 0;
    SET p_message = 'Ride is not currently in progress.';
  ELSE
    UPDATE Rides
    SET    ride_status = 'COMPLETED', completed_at = NOW()
    WHERE  ride_id = p_ride_id AND driver_id = p_driver_id;
    COMMIT;
    SET p_success = 1;
    SET p_message = 'Ride completed.';
  END IF;
END$$

-- sp_cancel_ride: cancel any active ride (REQUESTED / ACCEPTED / IN_PROGRESS)
-- Trigger trg_ride_closed handles driver availability if one was assigned.
CREATE PROCEDURE sp_cancel_ride(
  IN  p_ride_id INT,
  OUT p_success TINYINT,
  OUT p_message VARCHAR(200)
)
BEGIN
  DECLARE v_status VARCHAR(20);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    SET p_success = 0;
    SET p_message = 'Database error — ride could not be cancelled.';
  END;

  START TRANSACTION;

  SELECT ride_status INTO v_status FROM Rides WHERE ride_id = p_ride_id FOR UPDATE;

  IF v_status NOT IN ('REQUESTED','ACCEPTED','IN_PROGRESS') THEN
    ROLLBACK;
    SET p_success = 0;
    SET p_message = 'This ride cannot be cancelled.';
  ELSE
    UPDATE Rides SET ride_status = 'CANCELLED' WHERE ride_id = p_ride_id;
    COMMIT;
    SET p_success = 1;
    SET p_message = 'Ride cancelled.';
  END IF;
END$$

-- sp_generate_report: aggregate ride data and insert a Ride_Reports row atomically
CREATE PROCEDURE sp_generate_report(
  IN  p_admin_id    INT,
  IN  p_report_type VARCHAR(60),
  IN  p_date        DATE,
  IN  p_notes       TEXT,
  OUT p_report_id   INT,
  OUT p_success     TINYINT,
  OUT p_message     VARCHAR(200)
)
BEGIN
  DECLARE v_rides   INT           DEFAULT 0;
  DECLARE v_revenue DECIMAL(10,2) DEFAULT 0.00;
  DECLARE v_top_loc INT           DEFAULT NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    SET p_success = 0;
    SET p_message = 'Database error — report could not be generated.';
  END;

  START TRANSACTION;

  SELECT COUNT(*), COALESCE(SUM(fare_amount),0)
  INTO   v_rides, v_revenue
  FROM   Rides
  WHERE  DATE(requested_at) = p_date AND ride_status = 'COMPLETED';

  SELECT   pickup_location_id INTO v_top_loc
  FROM     Rides
  WHERE    DATE(requested_at) = p_date
  GROUP BY pickup_location_id
  ORDER BY COUNT(*) DESC
  LIMIT    1;

  INSERT INTO Ride_Reports
    (admin_id, report_type, report_date, total_rides, total_revenue, top_location_id, notes)
  VALUES
    (p_admin_id, p_report_type, p_date, v_rides, v_revenue, v_top_loc, p_notes);

  SET p_report_id = LAST_INSERT_ID();
  COMMIT;
  SET p_success = 1;
  SET p_message = CONCAT(p_report_type, ' for ', p_date,
                         ': ', v_rides, ' rides, M', FORMAT(v_revenue,2));
END$$

DELIMITER ;


-- ───────────────────────────────────────────────────────────────────
--  SECTION 5 — SEED DATA
-- ───────────────────────────────────────────────────────────────────

INSERT INTO Fares (zone_from, zone_to, amount) VALUES
  ('CBD',       'CBD',        80.00),
  ('CBD',       'MSU Local', 120.00),
  ('MSU Local', 'CBD',       120.00),
  ('MSU Local', 'MSU Local', 150.00);

INSERT INTO Locations (location_name, area_zone, description) VALUES
  ('Pioneer Mall',              'CBD',       'Main shopping centre'),
  ('Maseru Bridge',             'CBD ',  'Border crossing'),
  ('Maseru District Hospital',         'CBD ', 'Main referral hospital'),
  ('NRH Mall',        'CBD',       'small mall on kingsway rd'),
  ('Taxi Rank',             'CBD',       'Main transport hub'),
  ('Maseru Central Police',     'CBD',       'Central police station'),
  ('Koporasi',     'CBD',       'Setopo sa koporasi'),
  ('Maseru Mall',     'CBD',       'Shopping centre'),
  ('Lesotho Post Office',       'CBD',       'Main post office'),
  ('Mofumahali oa Tlholo',    'CBD', 'Kereke ea Roma e kholo'),
  ('Avani Hotel',         'CBD', 'Landmark hotel'),
  ('Sefika Complex',            'CBD',       'Commercial complex'),
  ('Alliance Française Maseru', 'CBD',  'French cultural centre'),
  ('Lancers Inn',               'CBD',       'CBD hotel'),
  ('Lesotho Bank Tower',        'CBD',       'Financial tower'),
  ('Ha Abia',                   'MSU Local', 'Local village near Maseru'),
  ('Ha Matala',                 'MSU Local', 'Local village near Maseru'),
  ('Ha Leqele',                 'MSU Local', 'Local village near Maseru'),
  ('Lithabaneng',               'MSU Local', 'Local village near Maseru'),
  ('Ha Pita',                   'MSU Local', 'Local village near Maseru'),
  ('Khubetsoana',               'MSU Local', 'Local village near Maseru'),
  ('Naleli',                    'MSU Local', 'Local village near Maseru'),
  ('Ha Thetsane',               'MSU Local', 'Local village near Maseru'),
  ('Sea Point',                 'MSU Local', 'Local village near Maseru'),
  ('Mohalalitoe',               'MSU Local', 'Local village near Maseru'),
  ('Hills View',                'MSU Local', 'Local village near Maseru');

INSERT INTO Payment_Methods (method_name, description) VALUES
  ('Cash', 'Physical cash'),
  ('Ecocash', 'Econet money transfer'),
  ('MPESA', 'Vodacom money transfer');

-- Admin: Admin@1234
INSERT INTO Admin_Users (username, email, password_hash, role) VALUES
  ('admin', 'admin@urbancab.co.ls',
   'bc78e58d55cde1346e68f8e5fe588dedf62fa457aa646a500a53347faff6ee24',
   'admin');

-- Drivers:
--   +26658200001 -> Mpho@1234
--   +26658200002 -> RetsTau@1234
--   +26658200003 -> Selibe@1234
INSERT INTO Drivers
  (first_name, last_name, phone_number, license_number,
   vehicle_plate, vehicle_model, password_hash, is_available)
VALUES
  ('Mpho', 'Letsie',   '+26658200001','LSO-DL-001','A 123 MS',
   'Toyota Corolla 2019',
   '00384db782b0f9fe1da2e884b438db3d9183470ed99eb7a9a8ff704965561a7e', 1),
  ('Rets''elisitsoe', 'Tau',      '+26658200002','LSO-DL-002','B 456 MS',
   'VW Polo 2020',
   '4c13160c02ae787e3f688d032145f36e503570f1f99b5ea1d048cb8d861829e0', 1),
  ('Selibe',        'Mokhothu', '+26658200003','LSO-DL-003','C 789 MS',
   'Honda Fit 2018',
   'ddbb9af440b078a0bbf7407b805bba01779e8b8d9141223429f2a16aee29e967', 0);

-- Sample rides — fare_amount omitted, trg_ride_set_fare calculates it
INSERT INTO Rides
  (passenger_name, passenger_phone, pickup_location_id, dropoff_location_id,
   driver_id, payment_method_id, ride_status, requested_at, accepted_at, completed_at)
VALUES
  ('Thabo Molefe',       '+26657100001', 1,  2, 1, 1, 'COMPLETED',
   '2025-01-10 08:05:00','2025-01-10 08:07:00','2025-01-10 08:22:00'),
  ('Nthabiseng Sithole', '+26657100002', 6,  3, 2, 2, 'COMPLETED',
   '2025-01-10 09:15:00','2025-01-10 09:17:00','2025-01-10 09:35:00'),
  ('Thabo Molefe',       '+26657100001', 4,  5, 1, 1, 'COMPLETED',
   '2025-01-11 07:45:00','2025-01-11 07:48:00','2025-01-11 08:00:00'),
  ('Lerato Mokoena',     '+26657100003', 1, 16, NULL, 1, 'REQUESTED',
   '2025-01-12 11:00:00', NULL, NULL);


-- ───────────────────────────────────────────────────────────────────
--  SECTION 6 — VERIFICATION
-- ───────────────────────────────────────────────────────────────────

SELECT '=== Tables ===' AS info;
SELECT table_name FROM information_schema.tables
WHERE  table_schema = 'urban_cab_db' AND table_type = 'BASE TABLE'
ORDER  BY table_name;

SELECT '=== Views ===' AS info;
SELECT table_name AS view_name FROM information_schema.views
WHERE  table_schema = 'urban_cab_db';

SELECT '=== Triggers ===' AS info;
SELECT trigger_name, event_manipulation AS event, event_object_table AS `table`
FROM   information_schema.triggers WHERE trigger_schema = 'urban_cab_db';

SELECT '=== Stored Procedures ===' AS info;
SELECT routine_name FROM information_schema.routines
WHERE  routine_schema = 'urban_cab_db' AND routine_type = 'PROCEDURE';

SELECT '=== Fares ===' AS info;
SELECT zone_from, zone_to, amount FROM Fares;

SELECT '=== Locations by zone ===' AS info;
SELECT area_zone, COUNT(*) AS count FROM Locations GROUP BY area_zone;

SELECT '=== Sample rides (fares auto-set by trigger) ===' AS info;
SELECT ride_id, passenger_name, ride_status, fare_amount FROM Rides;
