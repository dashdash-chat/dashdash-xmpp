GRANT USAGE ON *.* TO 'python-helper'@'localhost';
DROP USER 'python-helper'@'localhost';
CREATE USER 'python-helper'@'localhost' IDENTIFIED BY 'vap4yirck8irg4od4lo6';

DROP DATABASE IF EXISTS chatidea;
CREATE DATABASE chatidea;
USE chatidea;
GRANT SELECT,UPDATE ON chatidea.* TO 'python-helper'@'localhost';

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
