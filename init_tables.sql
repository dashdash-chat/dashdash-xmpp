DROP DATABASE IF EXISTS chatidea;
CREATE DATABASE chatidea;
USE chatidea;

DROP TABLE IF EXISTS users;
CREATE TABLE users (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user VARCHAR(15),
    created TIMESTAMP DEFAULT NOW()
);

DROP TABLE IF EXISTS proxybots;
CREATE TABLE proxybots (
    id CHAR(36) NOT NULL PRIMARY KEY,
    stage ENUM('idle', 'active', 'retired') NOT NULL,
    created TIMESTAMP DEFAULT NOW()
);
DROP TABLE IF EXISTS proxybot_participants;
CREATE TABLE proxybot_participants (
    proxybot_id CHAR(36) NOT NULL,
    FOREIGN KEY (proxybot_id) REFERENCES proxybots(id),
    user VARCHAR(15),
    created TIMESTAMP DEFAULT NOW()
);

DROP USER 'hostbot'@'localhost';
CREATE USER 'hostbot'@'localhost' IDENTIFIED BY 'ish9gen8ob8hap7ac9hy';
GRANT SELECT, UPDATE, INSERT, DELETE ON chatidea.users TO 'hostbot'@'localhost';
GRANT SELECT, UPDATE, INSERT, DELETE ON chatidea.proxybots TO 'hostbot'@'localhost';
GRANT SELECT, UPDATE, INSERT, DELETE ON chatidea.proxybot_participants TO 'hostbot'@'localhost';

DROP USER 'proxybotinfo'@'localhost';
CREATE USER 'proxybotinfo'@'localhost' IDENTIFIED BY 'oin9yef4aim9nott8if9';
GRANT SELECT ON chatidea.proxybots TO 'proxybotinfo'@'localhost';
GRANT SELECT ON chatidea.proxybot_participants TO 'proxybotinfo'@'localhost';

DROP USER 'userinfo'@'localhost';
CREATE USER 'userinfo'@'localhost' IDENTIFIED BY 'me6oth8ig3tot7as2ash';
GRANT SELECT ON chatidea.proxybots TO 'userinfo'@'localhost';
GRANT SELECT ON chatidea.proxybot_participants TO 'userinfo'@'localhost';

FLUSH PRIVILEGES;
