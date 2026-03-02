# Seshat Knowledge Base - Development Commands

.PHONY: help setup backend frontend clean install

help:
	@echo "Seshat Knowledge Base - Development Commands"
	@echo ""
	@echo "Available commands:"
	@echo "  setup     - Run the setup script to install dependencies"
	@echo "  backend   - Start the backend development server"
	@echo "  frontend  - Start the frontend development server"
	@echo "  install   - Install/update all dependencies"
	@echo "  clean     - Clean conda environment and node_modules"
	@echo ""

setup:
	@echo "Running setup script..."
	./setup.sh

backend:
	@echo "Starting backend server..."
	@echo "Make sure conda environment is activated: conda activate seshat-backend"
	cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

frontend:
	@echo "Starting frontend server..."
	cd frontend && npm run dev

install:
	@echo "Installing/updating dependencies..."
	cd backend && conda env update -f environment.yml
	cd frontend && npm install

clean:
	@echo "Cleaning up..."
	conda env remove -n seshat-backend -y || true
	rm -rf frontend/node_modules || true
	@echo "Run 'make setup' to reinstall"