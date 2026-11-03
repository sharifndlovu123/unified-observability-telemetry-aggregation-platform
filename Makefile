.PHONY: init verify scenario scenarios collector-reload routes up down logs test demo-user load
up:
	docker compose up -d --build --wait
down:
	docker compose down
logs:
	docker compose logs -f --tail=100
test:
	docker compose exec -T django pytest -q
demo-user:  ## users: demo / demo-pass (load) and ops-admin / ops-pass (staff, fault injection)
	docker compose exec -T django python manage.py create_demo_users
load:
	python3 scenarios/load/loadgen.py --duration 60 --rps 5
collector-reload:  ## re-render routing from EXPORT_* flags and restart the Collector
	docker compose up -d --force-recreate otel-config otel-collector
routes:  ## show where each signal is currently routed
	docker compose logs otel-config --no-log-prefix | tail -3
scenario:  ## run one operational scenario: make scenario N=1
	python3 scenarios/run.py $(N)
scenarios:  ## run all six scenarios (about 25 minutes)
	python3 scenarios/run.py all
init:  ## create .env with random secrets (first run only)
	python3 scripts/init_env.py
verify:  ## check the spec's acceptance criteria against the running stack
	python3 scenarios/verify.py
