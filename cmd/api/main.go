package main

import (
	"log/slog"
	"os"

	"github.com/mmiura-2351/mc-server-dashboard-api/internal/config"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	cfg, err := config.LoadAPI()
	if err != nil {
		logger.Error("failed to load config", "error", err)
		os.Exit(1)
	}

	logger.Info("api starting", "port", cfg.Port)
}
