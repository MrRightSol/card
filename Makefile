
.PHONY: fmt type test e2e up down postman

fmt:
	ruff check api || true
	black api || true
	isort api || true

type:
	mypy api || true

test:
	pytest -q api/tests

e2e:
	npx playwright test

up:
	docker compose up --build

down:
	docker compose down

postman:
	newman run postman/FraudCompliance.postman_collection.json --env-var base_url=http://localhost:8080
