build:
	docker compose build
	docker compose run --rm view yarn

build-prod:
	sudo docker-compose -f docker-compose.prod.yml build
	sudo docker-compose -f docker-compose.prod.yml run --rm view yarn
	sudo docker-compose -f docker-compose.prod.yml run --rm view yarn build
