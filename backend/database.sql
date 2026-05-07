-- prepares a MySQL server for the project
--create db name and user
CREATE DATABASE IF NOT EXISTS `twitter`;
USE `twitter`;
CREATE USER IF NOT EXISTS 'crud'@'localhost' IDENTIFIED WITH mysql_native_password BY '';
GRANT ALL PRIVILEGES ON `twitter`.* TO 'crud'@'localhost';
GRANT SELECT ON `performance_schema`.* TO 'crud'@'localhost';
FLUSH PRIVILEGES;

-- Accounts
CREATE TABLE IF NOT EXISTS accounts (
  id INT NOT NULL AUTO_INCREMENT,
  fullname VARCHAR(50) NOT NULL,
  username VARCHAR(50) NOT NULL,
  password VARCHAR(255) NOT NULL,
  email VARCHAR(255),
  profile_pic VARCHAR(255), -- Assuming storing the file path
  is_admin TINYINT(1) DEFAULT 0,
  account_status ENUM('Active', 'Disabled', 'Black Book') DEFAULT 'Active',
  can_post TINYINT(1) DEFAULT 1,
  black_label_count INT DEFAULT 0,
  bio VARCHAR(280),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS posts (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT,
    tweet TEXT,
    fullname VARCHAR(50) NOT NULL,
    username VARCHAR(50) NOT NULL,
    post_pic VARCHAR(255),
    profile_pic VARCHAR(255),-- Assuming the file path or URL of the post picture will be stored
    toxicity_label ENUM('Toxic', 'Non-Toxic') DEFAULT 'Non-Toxic',
    moderation_status ENUM('Approved', 'Rejected') DEFAULT 'Approved',
    moderation_reason VARCHAR(255),
    audience ENUM('Public', 'Friends', 'Only Me') DEFAULT 'Public',
    comments_enabled TINYINT(1) DEFAULT 1,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS moderation_terms (
    id INT PRIMARY KEY AUTO_INCREMENT,
    term VARCHAR(255) NOT NULL UNIQUE,
    translation VARCHAR(255),
    meaning TEXT,
    label ENUM('Toxic', 'Non-Toxic') NOT NULL,
    source VARCHAR(50) DEFAULT 'manual',
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS connections (
    id INT PRIMARY KEY AUTO_INCREMENT,
    requester_id INT NOT NULL,
    receiver_id INT NOT NULL,
    status ENUM('Pending', 'Accepted', 'Rejected') DEFAULT 'Pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_connection (requester_id, receiver_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INT PRIMARY KEY AUTO_INCREMENT,
    sender_id INT NOT NULL,
    receiver_id INT NOT NULL,
    message TEXT NOT NULL,
    toxicity_label ENUM('Toxic', 'Non-Toxic') DEFAULT 'Non-Toxic',
    moderation_status ENUM('Delivered', 'Rejected') DEFAULT 'Delivered',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS comments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    post_id INT NOT NULL,
    user_id INT NOT NULL,
    comment TEXT NOT NULL,
    toxicity_label ENUM('Toxic', 'Non-Toxic') DEFAULT 'Non-Toxic',
    moderation_status ENUM('Approved', 'Rejected') DEFAULT 'Approved',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reposts (
    id INT PRIMARY KEY AUTO_INCREMENT,
    post_id INT NOT NULL,
    user_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_repost (post_id, user_id)
);

CREATE TABLE IF NOT EXISTS likes (
    id INT PRIMARY KEY AUTO_INCREMENT,
    post_id INT NOT NULL,
    user_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_like (post_id, user_id)
);
);
