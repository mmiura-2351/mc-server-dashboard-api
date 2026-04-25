package main

import (
	"log/slog"
	"os"

	"github.com/mmiura-2351/mc-server-dashboard-api/internal/config"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	cfg, err := config.LoadRunnerAgent()
	if err != nil {
		logger.Error("failed to load config", "error", err)
		os.Exit(1)
	}

	logger.Info("runner-agent starting", "port", cfg.Port, "data_dir", cfg.MinecraftDataDir)
}
