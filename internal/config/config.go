package config

import (
	"fmt"
	"os"
	"strconv"
)

type API struct {
	Port                   string
	DatabaseURL            string
	RedisURL               string
	JWTSecret              string
	JWTExpiryHours         int
	RefreshTokenExpiryDays int
	LogLevel               string
}

func LoadAPI() (*API, error) {
	jwtExpiry, err := parseInt("JWT_EXPIRY_HOURS", 1)
	if err != nil {
		return nil, err
	}
	refreshExpiry, err := parseInt("REFRESH_TOKEN_EXPIRY_DAYS", 30)
	if err != nil {
		return nil, err
	}
	databaseURL, err := require("DATABASE_URL")
	if err != nil {
		return nil, err
	}
	redisURL, err := require("REDIS_URL")
	if err != nil {
		return nil, err
	}
	jwtSecret, err := require("JWT_SECRET")
	if err != nil {
		return nil, err
	}
	return &API{
		Port:                   getenv("PORT", "8080"),
		DatabaseURL:            databaseURL,
		RedisURL:               redisURL,
		JWTSecret:              jwtSecret,
		JWTExpiryHours:         jwtExpiry,
		RefreshTokenExpiryDays: refreshExpiry,
		LogLevel:               getenv("LOG_LEVEL", "info"),
	}, nil
}

type Worker struct {
	DatabaseURL       string
	RunnerAgentURL    string
	RunnerAgentToken  string
	JobPollIntervalMS int
	LogLevel          string
}

func LoadWorker() (*Worker, error) {
	pollInterval, err := parseInt("JOB_POLL_INTERVAL_MS", 500)
	if err != nil {
		return nil, err
	}
	databaseURL, err := require("DATABASE_URL")
	if err != nil {
		return nil, err
	}
	agentURL, err := require("RUNNER_AGENT_URL")
	if err != nil {
		return nil, err
	}
	agentToken, err := require("RUNNER_AGENT_TOKEN")
	if err != nil {
		return nil, err
	}
	return &Worker{
		DatabaseURL:       databaseURL,
		RunnerAgentURL:    agentURL,
		RunnerAgentToken:  agentToken,
		JobPollIntervalMS: pollInterval,
		LogLevel:          getenv("LOG_LEVEL", "info"),
	}, nil
}

type RunnerAgent struct {
	Port             string
	RunnerAgentToken string
	MinecraftDataDir string
	RedisURL         string
	LogLevel         string
}

func LoadRunnerAgent() (*RunnerAgent, error) {
	agentToken, err := require("RUNNER_AGENT_TOKEN")
	if err != nil {
		return nil, err
	}
	redisURL, err := require("REDIS_URL")
	if err != nil {
		return nil, err
	}
	return &RunnerAgent{
		Port:             getenv("PORT", "8081"),
		RunnerAgentToken: agentToken,
		MinecraftDataDir: getenv("MINECRAFT_DATA_DIR", "/data"),
		RedisURL:         redisURL,
		LogLevel:         getenv("LOG_LEVEL", "info"),
	}, nil
}

func require(key string) (string, error) {
	v := os.Getenv(key)
	if v == "" {
		return "", fmt.Errorf("required environment variable %q is not set", key)
	}
	return v, nil
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func parseInt(key string, fallback int) (int, error) {
	v := os.Getenv(key)
	if v == "" {
		return fallback, nil
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return 0, fmt.Errorf("environment variable %q must be an integer: %w", key, err)
	}
	return n, nil
}
