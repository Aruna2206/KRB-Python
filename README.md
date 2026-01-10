# KRB PORTAL - Backend API

This is the backend API for the KRB Portal, built with Python, FastAPI, and MongoDB.

## Prerequisites

- **Python 3.8+**: Ensure you have a modern version of Python installed.
- **MongoDB**: You need a running MongoDB instance.

## Installation

1.  **Navigate to the backend directory:**
    ```bash
    cd "Backend/KRB Python"
    ```

2.  **Create a virtual environment:**
    ```bash
    python -m venv venv
    ```

3.  **Activate the virtual environment:**
    - On Windows:
        ```bash
        venv\Scripts\activate
        ```
    - On macOS/Linux:
        ```bash
        source venv/bin/activate
        ```

4.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

1.  Create a `.env` file in the root of the `Backend/KRB Python` directory.
2.  Add the following environment variables (adjust values as needed):

    ```env
    # Database Connection
    MONGODB_URL=mongodb://localhost:27017

    # Security
    SECRET_KEY=your-secure-secret-key-change-this-in-production
    ```

## Running the Application

You can start the server using Uvicorn directly or via the helper script in `main.py`.

### Option 1: Using Python (Recommended for dev)
This will run the server on `0.0.0.0:8000`.
```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Option 2: Using Uvicorn Command
```bash
uvicorn main:app --reload
```

## API Documentation

Once the server is running, you can access the interactive API documentation at:

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

## Project Structure

- **`main.py`**: Application entry point.
- **`config.py`**: Database connection and configuration settings.
- **`dependencies.py`**: Authentication logic and dependency injection.
- **`models.py`**: Pydantic models for data validation.
- **`routers/`**: Contains the API route logic (admin, auth, etc.).
