-- GRANT USAGE ON *.* TO 'python-helper'@'localhost';
-- DROP USER 'python-helper'@'localhost';
-- CREATE USER 'python-helper'@'localhost' IDENTIFIED BY 'vap4yirck8irg4od4lo6';
-- CREATE USER 'userinfo-helper'@'localhost' IDENTIFIED BY 'rycs3yuf8of4vit9fac3';
-- GRANT SELECT ON chatidea.convo_starts TO 'userinfo-helper'@'localhost';

-- DROP DATABASE IF EXISTS chatidea;
-- CREATE DATABASE chatidea;
CREATE DATABASE chatidea_state;
USE chatidea;
-- GRANT SELECT,UPDATE ON chatidea.* TO 'python-helper'@'localhost';
GRANT ALL ON chatidea_state.* TO 'python-helper'@'localhost';
-- 
-- CREATE TABLE users (
--     id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
--     username VARCHAR(15),
-- 		has_jid BOOLEAN NOT NULL DEFAULT 0,
--     created TIMESTAMP DEFAULT NOW()
-- );
-- INSERT INTO users (username) VALUES ('alice');
-- INSERT INTO users (username) VALUES ('chesire_cat');
-- INSERT INTO users (username) VALUES ('dormouse');
-- INSERT INTO users (username) VALUES ('hatter');
-- INSERT INTO users (username) VALUES ('march_hare');
-- INSERT INTO users (username) VALUES ('white_rabbit');
-- INSERT INTO users (username) VALUES ('queen_of_hearts');

DROP TABLE IF EXISTS convo_starts;
CREATE TABLE convo_starts (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    sender VARCHAR(15),
    recipient VARCHAR(15),
	count INT UNSIGNED NOT NULL DEFAULT 0,
    created TIMESTAMP DEFAULT NOW()
);
INSERT INTO convo_starts (count, sender, recipient) VALUES (45, 'alice', 'chesire_cat');
INSERT INTO convo_starts (count, sender, recipient) VALUES (50, 'chesire_cat', 'alice');
INSERT INTO convo_starts (count, sender, recipient) VALUES (13, 'alice', 'dormouse');
INSERT INTO convo_starts (count, sender, recipient) VALUES (10, 'dormouse', 'alice');
INSERT INTO convo_starts (count, sender, recipient) VALUES (4, 'dormouse', 'chesire_cat');
INSERT INTO convo_starts (count, sender, recipient) VALUES (4, 'chesire_cat', 'dormouse');
INSERT INTO convo_starts (count, sender, recipient) VALUES (24, 'queen_of_hearts', 'alice');
INSERT INTO convo_starts (count, sender, recipient) VALUES (10, 'queen_of_hearts', 'dormouse');
INSERT INTO convo_starts (count, sender, recipient) VALUES (10, 'queen_of_hearts', 'chesire_cat');

INSERT INTO convo_starts (count, sender, recipient) VALUES (0, 'march_hare', 'queen_of_hearts');
INSERT INTO convo_starts (count, sender, recipient) VALUES (2, 'queen_of_hearts', 'march_hare');
INSERT INTO convo_starts (count, sender, recipient) VALUES (1, 'alice', 'queen_of_hearts');

DROP TABLE IF EXISTS cur_proxybots;
CREATE TABLE cur_proxybots (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user1 VARCHAR(15),
    user2 VARCHAR(15),
    created TIMESTAMP DEFAULT NOW()
);

CREATE TABLE cur_proxybots (id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, user1 VARCHAR(15), user2 VARCHAR(15), created TIMESTAMP DEFAULT NOW() );