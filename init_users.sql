DROP DATABASE IF EXISTS chatidea;
CREATE DATABASE chatidea;
USE chatidea;

DROP TABLE IF EXISTS users;
CREATE TABLE users (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(15),
	has_jid BOOLEAN NOT NULL DEFAULT 0,
    created TIMESTAMP DEFAULT NOW()
);
INSERT INTO users (username) VALUES ('alice');
INSERT INTO users (username) VALUES ('chesire_cat');
INSERT INTO users (username) VALUES ('dormouse');
INSERT INTO users (username) VALUES ('hatter');
INSERT INTO users (username) VALUES ('march_hare');
INSERT INTO users (username) VALUES ('white_rabbit');
INSERT INTO users (username) VALUES ('queen_of_hearts');

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

-- DROP TABLE IF EXISTS cur_proxybots;
-- CREATE TABLE cur_proxybots (
--     id INT UNSIGNED NOT NULL PRIMARY KEY,
--     created TIMESTAMP DEFAULT NOW()
-- );
-- DROP TABLE IF EXISTS cur_proxybot_participants;
-- CREATE TABLE cur_proxybot_participants (
--     proxybot_id INT UNSIGNED NOT NULL PRIMARY KEY,
-- 	FOREIGN KEY (proxybot_id) REFERENCES cur_proxybots(id),
-- 	user VARCHAR(15),
--     created TIMESTAMP DEFAULT NOW()
-- );

DROP USER 'hostbot'@'localhost';
CREATE USER 'hostbot'@'localhost' IDENTIFIED BY 'ish9gen8ob8hap7ac9hy';
GRANT SELECT, UPDATE ON chatidea.users TO 'hostbot'@'localhost';
GRANT ALL ON chatidea.cur_proxybots TO 'hostbot'@'localhost';
GRANT ALL ON chatidea.cur_proxybot_participants TO 'hostbot'@'localhost';

DROP USER 'userinfo'@'localhost';
CREATE USER 'userinfo'@'localhost' IDENTIFIED BY 'me6oth8ig3tot7as2ash';
GRANT SELECT,UPDATE ON chatidea.convo_starts TO 'userinfo'@'localhost';

FLUSH PRIVILEGES;
