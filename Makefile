.PHONY: up down status logs provision test validate demo chaos-latency chaos-errors chaos-reset

up:
	docker compose up -d --build

down:
	docker compose down

status:
	docker compose ps

logs:
	docker compose logs -f --tail=100

provision:
	docker compose run --rm zabbix-provision

test:
	python3 -m pytest -q

validate:
	docker compose config -q
	python3 -m compileall -q app scripts zabbix/provision notifier tests

demo:
	curl --fail http://127.0.0.1:8080/produtos
	curl --fail -X POST http://127.0.0.1:8080/pedidos \
		-H 'Content-Type: application/json' \
		-d '{"produto_id":1,"quantidade":1}'

chaos-latency:
	curl --fail -X POST http://127.0.0.1:8080/admin/caos \
		-H "X-Admin-Token: $${ADMIN_TOKEN:-somente-laboratorio-local}" \
		-H 'Content-Type: application/json' -d '{"latencia_ms":800}'

chaos-errors:
	curl --fail -X POST http://127.0.0.1:8080/admin/caos \
		-H "X-Admin-Token: $${ADMIN_TOKEN:-somente-laboratorio-local}" \
		-H 'Content-Type: application/json' -d '{"taxa_erro":0.2}'

chaos-reset:
	curl --fail -X POST http://127.0.0.1:8080/admin/caos \
		-H "X-Admin-Token: $${ADMIN_TOKEN:-somente-laboratorio-local}" \
		-H 'Content-Type: application/json' -d '{"latencia_ms":0,"taxa_erro":0}'
