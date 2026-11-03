.PHONY: up down logs test demo-user load
up:
	docker compose up -d --build --wait
down:
	docker compose down
logs:
	docker compose logs -f --tail=100
test:
	docker compose exec -T django pytest -q
demo-user:
	docker compose exec -T django python manage.py shell -c "from django.contrib.auth.models import User; User.objects.filter(username='demo').exists() or User.objects.create_user('demo', password='demo-pass')"
load:
	python3 scenarios/load/loadgen.py --duration 60 --rps 5
