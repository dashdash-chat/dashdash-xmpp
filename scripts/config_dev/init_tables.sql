DROP DATABASE IF EXISTS vine;
CREATE DATABASE vine;
USE vine;

DROP TABLE IF EXISTS users;
CREATE TABLE users (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user VARCHAR(15),
    UNIQUE(user),
    created TIMESTAMP DEFAULT NOW()
);

DROP TABLE IF EXISTS pair_vinebots;
CREATE TABLE pair_vinebots (
    id BINARY(16) NOT NULL,
    user1 INT NOT NULL,
    user2 INT NOT NULL,
    FOREIGN KEY (user1) REFERENCES users(id),
    FOREIGN KEY (user2) REFERENCES users(id),
    UNIQUE KEY user1 (user1, user2),
    is_active BOOLEAN NOT NULL DEFAULT FALSE
);
DROP TABLE IF EXISTS party_vinebots;
CREATE TABLE party_vinebots (
    id BINARY(16) NOT NULL,
    user INT NOT NULL,
    FOREIGN KEY (user) REFERENCES users(id),
    UNIQUE KEY membership (id, user)
);

DROP USER 'leaf1'@'localhost';
CREATE USER 'leaf1'@'localhost' IDENTIFIED BY 'ish9gen8ob8hap7ac9hy';
GRANT SELECT, UPDATE, INSERT, DELETE ON vine.users TO 'leaf1'@'localhost';
GRANT SELECT, UPDATE, INSERT, DELETE ON vine.pair_vinebots TO 'leaf1'@'localhost';
GRANT SELECT, UPDATE, INSERT, DELETE ON vine.party_vinebots TO 'leaf1'@'localhost';

FLUSH PRIVILEGES;
