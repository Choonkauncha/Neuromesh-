.PHONY: build test smoke
build:
	shards build
test: build
	crystal spec
	python3 -m unittest eval.test_eval
smoke: build
	./bin/neuromesh --objective gateway-smoke --log logs/gateway-smoke.jsonl
