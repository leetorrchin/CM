.PHONY: run dev test web docker
run:        ## build and start everything on :8000
	./run.sh
dev:        ## server plus Vite hot reload
	./run.sh dev
test:       ## Python and web tests
	uv run pytest -q
	cd viz && npm test --silent
web:        ## build the web apps only
	cd viz && npm run build
docker:     ## same thing in a container
	docker compose up --build
