-- DAY 3 — MediCheck 데이터베이스 스키마
-- MySQL 8.0+

CREATE DATABASE IF NOT EXISTS medicheck
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE medicheck;

-- 병원 테이블
CREATE TABLE IF NOT EXISTS hospitals (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(100)  NOT NULL,
  phone         VARCHAR(20),
  address       VARCHAR(200),
  hours         VARCHAR(300),
  place_url     VARCHAR(500),
  lat           DOUBLE,
  lng           DOUBLE,
  ai_summary    JSON,
  premium_rank  INT DEFAULT 0,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  INDEX idx_name (name),
  INDEX idx_premium (premium_rank)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 사용자 테이블
CREATE TABLE IF NOT EXISTS users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  email         VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  INDEX idx_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 리뷰 테이블
CREATE TABLE IF NOT EXISTS reviews (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  hospital_id   INT NOT NULL,
  review_text   TEXT,
  rating        TINYINT,
  review_date   DATE,

  FOREIGN KEY (hospital_id) REFERENCES hospitals(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE,

  INDEX idx_hospital (hospital_id),
  INDEX idx_rating   (rating),
  INDEX idx_date     (review_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 즐겨찾기 테이블
CREATE TABLE IF NOT EXISTS favorites (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  user_id       INT NOT NULL,
  hospital_id   INT NOT NULL,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  FOREIGN KEY (hospital_id) REFERENCES hospitals(id)
    ON DELETE CASCADE ON UPDATE CASCADE,

  UNIQUE KEY uq_user_hospital (user_id, hospital_id),
  INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
