# Everyday commands. `make` alone starts everything and runs the bot.
.DEFAULT_GOAL := run
.PHONY: run up down test logs deploy help
.NOTPARALLEL:  # steps depend on each other, even under `make -j`

DEV := docker compose -f docker-compose.dev.yml
TEST_DB := POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_PASSWORD=devpassword

help:            ## List the commands
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

run: up         ## Start Postgres and TibiaData if needed, then run the bot
	uv sync --quiet
	uv run tibiabot

up:             ## Start the dev Postgres (:5433) and TibiaData (:8081), waiting until ready
	@docker info >/dev/null 2>&1 || { echo "Docker is not running. Start it: sudo systemctl start docker"; exit 1; }
	$(DEV) up -d --wait

down:           ## Stop the dev containers (data is kept)
	$(DEV) down

test: up        ## Run all tests, database ones included
	uv sync --quiet
	$(TEST_DB) uv run pytest -q

logs:           ## Follow the dev containers' logs
	$(DEV) logs -f

deploy:         ## Production: build and start bot + Postgres + TibiaData (docker-compose.yml)
	docker compose up -d --build
	docker compose logs -f bot
