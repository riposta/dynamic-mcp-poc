.PHONY: up down status test test-smoke test-install info logs keycloak servers gateway agent wait-keycloak wait-servers wait-gateway wait-agent setup-keycloak

PYTHON     ?= python
VENV       := .venv/bin/python
PID_DIR    := .pids
LOG_DIR    := .logs

# ── Full environment ─────────────────────────────────────────────

up: keycloak wait-keycloak setup-keycloak servers wait-servers gateway wait-gateway agent wait-agent info

down:
	@echo "Stopping services..."
	@for port in 8000 8010 8011 8012; do \
		pid=$$(lsof -t -i :$$port 2>/dev/null); \
		if [ -n "$$pid" ]; then \
			kill $$pid 2>/dev/null; \
			echo "  Killed PID $$pid on port $$port"; \
		fi; \
	done
	@rm -rf $(PID_DIR) $(LOG_DIR)
	@echo "Stopping Keycloak..."
	@docker compose down
	@echo "All services stopped."

# ── Individual components ────────────────────────────────────────

keycloak:
	@echo "Starting Keycloak..."
	@docker compose up -d

servers: $(PID_DIR) $(LOG_DIR)
	@echo "Starting Weather server on :8011..."
	@$(VENV) servers/weather_server.py >> $(LOG_DIR)/weather.log 2>&1 & echo $$! > $(PID_DIR)/weather.pid
	@echo "Starting Calculator server on :8012..."
	@$(VENV) servers/calculator_server.py >> $(LOG_DIR)/calculator.log 2>&1 & echo $$! > $(PID_DIR)/calculator.pid

gateway: $(PID_DIR) $(LOG_DIR)
	@echo "Starting Gateway on :8010..."
	@$(VENV) gateway/server.py >> $(LOG_DIR)/gateway.log 2>&1 & echo $$! > $(PID_DIR)/gateway.pid

agent: $(PID_DIR) $(LOG_DIR)
	@echo "Starting Agent Web UI on :8000..."
	@$(VENV) agent/web.py >> $(LOG_DIR)/agent.log 2>&1 & echo $$! > $(PID_DIR)/agent.pid

$(PID_DIR) $(LOG_DIR):
	@mkdir -p $@

# ── Wait targets ─────────────────────────────────────────────────

wait-keycloak:
	@printf "Waiting for Keycloak"
	@for i in $$(seq 1 60); do \
		if curl -sf http://localhost:8080/realms/mcp-poc > /dev/null 2>&1; then \
			echo " ready"; \
			break; \
		fi; \
		printf "."; \
		sleep 2; \
		if [ $$i -eq 60 ]; then echo " TIMEOUT"; exit 1; fi; \
	done

setup-keycloak:
	@echo "Configuring token exchange permissions..."
	@bash keycloak/setup-permissions.sh

wait-servers:
	@printf "Waiting for MCP servers"
	@for i in $$(seq 1 15); do \
		if curl -so /dev/null -w "" http://localhost:8011/mcp 2>/dev/null && curl -so /dev/null -w "" http://localhost:8012/mcp 2>/dev/null; then \
			echo " ready"; \
			break; \
		fi; \
		printf "."; \
		sleep 1; \
		if [ $$i -eq 15 ]; then echo " TIMEOUT"; exit 1; fi; \
	done

wait-gateway:
	@printf "Waiting for Gateway"
	@for i in $$(seq 1 15); do \
		if curl -so /dev/null -w "" http://localhost:8010/mcp 2>/dev/null; then \
			echo " ready"; \
			break; \
		fi; \
		printf "."; \
		sleep 1; \
		if [ $$i -eq 15 ]; then echo " TIMEOUT"; exit 1; fi; \
	done

wait-agent:
	@printf "Waiting for Agent"
	@for i in $$(seq 1 15); do \
		if curl -sf http://localhost:8000/ > /dev/null 2>&1; then \
			echo " ready"; \
			break; \
		fi; \
		printf "."; \
		sleep 1; \
		if [ $$i -eq 15 ]; then echo " TIMEOUT"; exit 1; fi; \
	done

# ── Logs ────────────────────────────────────────────────────────

logs:
	@tail -f $(LOG_DIR)/*.log

# ── Tests ────────────────────────────────────────────────────────

test-install:
	@cd tests/bdd && npm install

test:
	@cd tests/bdd && npm test

test-smoke:
	@cd tests/bdd && npm run test:smoke

# ── Info ─────────────────────────────────────────────────────────

status:
	@echo ""
	@echo "=== Service Status ==="
	@printf "  Keycloak     :8080  "; curl -sf http://localhost:8080/realms/mcp-poc > /dev/null 2>&1 && echo "UP" || echo "DOWN"
	@printf "  Weather      :8011  "; curl -so /dev/null -w "" http://localhost:8011/mcp 2>/dev/null && echo "UP" || echo "DOWN"
	@printf "  Calculator   :8012  "; curl -so /dev/null -w "" http://localhost:8012/mcp 2>/dev/null && echo "UP" || echo "DOWN"
	@printf "  Gateway      :8010  "; curl -so /dev/null -w "" http://localhost:8010/mcp 2>/dev/null && echo "UP" || echo "DOWN"
	@printf "  Agent Web UI :8000  "; curl -sf http://localhost:8000/ > /dev/null 2>&1 && echo "UP" || echo "DOWN"
	@echo ""

info:
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║              MCP Gateway PoC -- Environment Ready           ║"
	@echo "╠══════════════════════════════════════════════════════════════╣"
	@echo "║                                                             ║"
	@echo "║  Services:                                                  ║"
	@echo "║    Keycloak          http://localhost:8080                   ║"
	@echo "║    MCP Gateway       http://localhost:8010/mcp              ║"
	@echo "║    Weather Server    http://localhost:8011/mcp              ║"
	@echo "║    Calculator Server http://localhost:8012/mcp              ║"
	@echo "║    Agent Web UI      http://localhost:8000                  ║"
	@echo "║                                                             ║"
	@echo "║  Keycloak Admin Console:                                    ║"
	@echo "║    URL:       http://localhost:8080/admin                    ║"
	@echo "║    Username:  admin                                         ║"
	@echo "║    Password:  admin                                         ║"
	@echo "║    Realm:     mcp-poc                                       ║"
	@echo "║                                                             ║"
	@echo "║  Test Users:                                                ║"
	@echo "║    testuser / testpass     (weather + calculator)           ║"
	@echo "║    limiteduser / testpass  (weather only)                   ║"
	@echo "║                                                             ║"
	@echo "║  Keycloak Clients:                                          ║"
	@echo "║    adk-web-client       public (PKCE)                       ║"
	@echo "║    mcp-gateway          secret: mcp-gateway-secret          ║"
	@echo "║    mcp-weather          secret: mcp-weather-secret          ║"
	@echo "║    mcp-calculator       secret: mcp-calculator-secret       ║"
	@echo "║                                                             ║"
	@echo "║  Commands:                                                  ║"
	@echo "║    make down        Stop everything                         ║"
	@echo "║    make status      Check service health                    ║"
	@echo "║    make test        Run BDD tests                           ║"
	@echo "║    make test-smoke  Run smoke tests only                    ║"
	@echo "║    make logs        Tail all service logs                   ║"
	@echo "║                                                             ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
