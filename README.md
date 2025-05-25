# Dockerized Combined App with MQTT Broker and Background Task

This repository now uses a single container ("combined_app") to run all three processes:

- Streamlit App
- MQTT Broker
- Background Task

The processes are coordinated by main.py.

## Prerequisites

- Docker
- Docker Compose
- [Recommended] Visual Studio Code with the following extensions installed:
  - Mypy (ms-python.mypy-type-checker)
  - Pylint (ms-python.pylint)
  - Black Formatter (ms-python.black-formatter)

**NOTE**: Using these extensions will provide in-editor warnings and help you format your code correctly before running the linter.

**NOTE**: you have this stored and running in a folder called `integration` as the docker-compose.yml file references the current directory, auto-generated names will rely on this (so some steps below won't work if you call it something else).

## Setup and Run

1. Clone the repository:

   ```sh
   git clone https://github.com/Hurtec/integration.git
   cd integration
   ```

2. Create configuration files (documented below)

   1. `.secrets/secrets.toml` (for app login & router info)

3. Build and start the combined Docker container:

   ```sh
   docker-compose up --build
   ```

   The combined container will start web_app, background_task, and mqtt_broker via main.py.

4. Access the Web app running in Docker:

   Open your web browser and go to `http://localhost:8088`.

### Development Mode with Mock Services

For local development without connecting to real external services (like the Peplink router), you can use the "mock mode":

1. The docker-compose.yml file already includes the `MOCK_MODE: "true"` environment variable for local development.

2. When running in mock mode:
   - The background task will generate simulated GPS data instead of connecting to the router
   - The background task will generate simulated vehicle data with ignition on/off events:
     - Initial state: ignition ON (ign_state=True)
     - After ~60 seconds: ignition OFF (ign_state=False)
   - No connection to the router is attempted at all (no GPS or vehicle data fetching)
   - The web interface will display a "MOCK MODE" indicator
   - All other functionality remains unchanged:
     - Real PostgreSQL database is still used
     - Real MQTT broker is still used
     - All background tasks and heartbeats run normally

3. Mock mode is completely independent from the environment setting (test/prod/dev):
   - You can run mock mode with any environment setting
   - The environment setting controls AWS IoT topic prefixes
   - Mock mode only affects GPS and vehicle data generation

4. This allows for testing and development without requiring actual hardware connections.

### Generate a Hashed Password

Since you're running the application inside Docker, you need to execute the `hash_password.py` script within the Docker container. Follow these steps:

1. **Run the `hash_password.py` Script Inside Docker:**

   First, build to make sure the container is up-to-date:

   ```sh
   docker-compose up --build --remove-orphans
   ```

   Then stop the container, and run:

   ```sh
   docker-compose run --rm combined_app python hash_password.py
   ```

   - **What This Does:**
     - **`docker-compose run`**: Runs a one-time command against the `combined_app` service defined in your `docker-compose.yml`.
     - **`--rm`**: Automatically removes the container after the command completes.
     - **`combined_app`**: The service where the script will run.
     - **`python hash_password.py`**: Executes the `hash_password.py` script inside the container.

2. **Enter Your Desired Password:**

   When prompted, input the password you wish to hash.

   ```sh
   Enter password to hash: your_password_here
   ```

   The script will output something like:

   ```sh
   Hashed password: $2b$12$Saltsaltsaltsaltsaltsaltedhashedpassword1234567890
   ```

3. **Create or update `secrets.toml` with the Hashed Password:**

   Open the `.secrets/secrets.toml` file located at `/src/.secrets/secrets.toml` and replace the placeholder with your newly generated hashed password.

   ```plaintext
   [passwords]
   # Follow the rule: username = "hashed_password"
   admin = "$2b$12$Saltsaltsaltsaltsaltsaltedhashedpassword1234567890"  # Replace with the actual bcrypt hashed password
   ```

## Background Task Secrets

The Background Task requires its own set of credentials to interact with the Peplink router's API. Follow these steps to configure the Background Task secrets:

1. **Create or update `.secrets/secrets.toml`:**

   On the local machine where you are building the Docker containers, create a directory named `.secrets` in the root of the project and then create a file named `background_task_secrets.toml` inside it.

   ```plaintext
   /src/.secrets/secrets.toml
   ```

2. **Add Peplink API Credentials:**

   Populate the `.secrets/secrets.toml` file with your Peplink router's IP address, a an admin UserId and Password. The credentials can be found in `Settings > Device System Management`.

   ```plaintext
   [peplink_api]
   router_ip = "192.168.82.1"
   router_userid = "admin"
   router_password = "some-hashed-value-here"
   ```

   Note: the Peplink API documentation can be found at: [Peplink API Documentation](https://download.peplink.com/resources/Peplink-Router-API-Documentation-for-Firmware-8.1.1.pdf). We are using the [Transit Pro E](https://www.peplink.com/products/mobile-routers/max-transit-pro-e/) at the time of writing.

## Web App

The Web app requires a login. You can set up credentials by creating a file `.secrets/secrets.toml` with the following content, changing the username(s) and password(s) as needed - see above if you need to generate a password.

### Upload Certificate Files

1. Go to the "Upload Certificate Files" section.
2. Choose a certificate file (e.g., `ca.pem`, `cert.crt`, `private.key`) and upload it.
3. The uploaded files will be saved to the shared volume.

### Enter Configuration

1. Go to the "Enter Configuration" section.
2. Enter the tenant name and device name.
3. Click the "Save Configuration" button.
4. The configuration will be saved to the shared volume.

### View MQTT Messages

1. Go to the "View MQTT Messages" section.
2. The app will display the MQTT messages stored in the shared SQLite database (`shared_data.db`).

### Service Status Monitoring

The application uses a shared SQLite database (`shared_data.db`) to monitor the status of the MQTT Broker and Background Task services. Status information is stored in the `service_status` table within the database and is displayed in the Web app.

#### Viewing Service Status

1. Open the Web app at `http://localhost:8088`.
2. Navigate to the "Service Status" section.
3. View the current status of the MQTT Broker and Background Task services, including when they started and their local and UTC times.

This feature ensures that you can monitor whether all necessary configurations are in place and whether the services are running correctly.

## Database Management

The application uses PostgreSQL for data storage.

### Setting Up Python Locally and Running Migrations

This project uses `uv` as the Python package manager for a streamlined development experience.

You need to start your local `integration-postgres` container before running alembic commands.

To start the container, run:

```sh
docker-compose up -d postgres
```

#### Setting Up with UV

1.  **Install `uv` (if not already installed)**:

     Follow the instructions at [https://github.com/astral-sh/uv](https://github.com/astral-sh/uv)

2.  **Create a virtual environment**:

     ```sh
     uv venv
     ```

3.  **Activate the virtual environment**:

     -   On Windows:
         ```sh
         .\.venv\Scripts\activate
         ```
     -   On macOS/Linux:
         ```sh
         source .venv/bin/activate
         ```

4.  **Install the required packages**:

     ```sh
     uv pip install -r requirements-combined.txt
     uv pip install -r requirements-dev.txt
     ```

5.  **Run Alembic commands**:

     First, change to the `src` directory, E.g `cd src`.

     ```sh
     # With environment activated
     alembic revision --autogenerate -m "migration_name"
     alembic upgrade head

     # Or using uv run (without activating environment)
     uv run alembic revision --autogenerate -m "migration_name"
     uv run alembic upgrade head
     ```

     When creating a migration:
     1. Come up with a short migration name that describes what database change you're making, e.g., "add_bms_data".
     2. Run the command `alembic revision --autogenerate -m "migration_name"` - this should create a new migration file in `src\migrations\versions`.
     3. Review the migration file carefully and make sure it looks correct - it can be difficult to "undo" or change things in the database, so it's better to get it right the first time if possible. If you need to make further changes, you can delete the migration file and re-generate it at this stage.
     4. Once you're happy with the migration, with postgres running as per the step above, run `alembic upgrade head` to apply the changes.
     5. If there are no errors, you should be able to run the whole app now and the database changes should be applied.

     Note: The application will automatically detect if it's running locally or in Docker and use the appropriate database host (localhost for local development, postgres for Docker containers).

# Making code changes

## Running Tests

To run the tests, you'll need to have your Python environment set up using `uv` as described in the Database Management section.

### Using Docker Compose

Run the tests using `docker-compose` (so that you don't need a local python environment set up):

```sh
docker-compose -p integration-dev -f docker-compose-dev.yml up --build --force-recreate test --remove-orphans
```

### Local Python Environment

If you have a local Python environment set up:

1.  **Ensure you're in the correct environment**:
    ```sh
    source .venv/bin/activate  # On Linux/macOS
    .\.venv\Scripts\activate   # On Windows
    ```

2.  **Install test dependencies** (if not already done):
    ```sh
    uv pip install -r requirements-dev.txt
    uv pip install -r requirements-combined.txt
    ```

3.  **Run the tests**:

    *   **With environment activated:**
        ```sh
        # On Linux/macOS
        PYTHONPATH=src pytest tests/ -v --timeout=30

        # On Windows PowerShell
        $env:PYTHONPATH = 'src'; pytest tests/ -v --timeout=30
        ```
        *   Run a specific test file:
            ```sh
            # On Linux/macOS
            PYTHONPATH=src pytest tests/test_background_task.py -v --timeout=30
            # On Windows PowerShell
            $env:PYTHONPATH = 'src'; pytest tests/test_background_task.py -v --timeout=30
            ```
        *   Run a specific test:
            ```sh
            # On Linux/macOS
            PYTHONPATH=src pytest tests/test_background_task.py::test_process_gps_data_success -v --timeout=30
            # On Windows PowerShell
            $env:PYTHONPATH = 'src'; pytest tests/test_background_task.py::test_process_gps_data_success -v --timeout=30
            ```

    *   **Using `uv run` (environment activation not needed):**
        ```sh
        # On Linux/macOS (uv run inherits current env vars)
        PYTHONPATH=src uv run pytest tests/ -v --timeout=30

        # On Windows PowerShell
        $env:PYTHONPATH = 'src'; uv run pytest tests/ -v --timeout=30
        ```

    Note: On Windows PowerShell, use `$env:PYTHONPATH = "src"` instead when running directly:
    ```powershell
    $env:PYTHONPATH = "src"; pytest tests/ -v --timeout=30
    ```
    When using `uv run` on PowerShell, you might need to set the environment variable differently depending on your shell configuration or use `uv run --env PYTHONPATH=src -- ...` syntax if supported.

## Linting and Testing

You can run linting and tests separately or together using Docker Compose.

### Docker Compose

#### Run Linting Only

Run the linter using `docker-compose` (so that you don't need a local python environment set up):

```sh
docker-compose -p integration-dev -f docker-compose-dev.yml up --build --force-recreate linter --remove-orphans
```

#### Run Tests Only

Run the tests using `docker-compose`:

```sh
docker-compose -p integration-dev -f docker-compose-dev.yml up --build --force-recreate test --remove-orphans
```

#### Run Both Linting and Tests

Run both linting and tests in one go:

```sh
docker-compose -p integration-dev -f docker-compose-dev.yml up --build --force-recreate lint-test --remove-orphans
```

### Local Python Environment

If you have run the steps above around managing database migrations, you may already have a local python virtual environment set up with `uv`. If that is the case, it may be quicker to run linting locally:

1.  **Ensure you're in the correct environment**:
    ```sh
    source .venv/bin/activate  # On Linux/macOS
    .\.venv\Scripts\activate   # On Windows
    ```

2.  **Ensure requirements are installed** (if not already done):
    ```sh
    uv pip install -r requirements-dev.txt
    uv pip install -r requirements-combined.txt
    ```

3.  **Run linters**:
    ```sh
    # To run Black formatter (with environment activated)
    black .
    # Or using uv run
    uv run black .

    # To run Pylint (with environment activated)
    # Use specific paths to avoid linting packages in the virtual environment
    pylint src/ --rcfile=pylintrc --ignore=migrations
    # Or using uv run (from project root)
    uv run pylint src/ --rcfile=pylintrc --ignore=migrations

    # To run mypy (with environment activated)
    mypy --install-types
    mypy --config-file=mypy.ini src
    # Or using uv run
    uv run mypy --install-types
    uv run mypy --config-file=mypy.ini src
    ```

    **Note**: When running Pylint, always specify explicit paths (`src/` and `tests/`) to avoid analyzing files in the virtual environment's site-packages directory.

# Deploying to Docker Hub

## Automated Deployment with GitHub Actions

This repository uses GitHub Actions to automatically validate code and deploy Docker images.

### GitHub Actions Workflows

1. **PR Build Workflow**
   - Runs automatically when a pull request is created against the main branch
   - Validates code quality (formatting, linting, type checking)
   - Runs all tests to ensure functionality
   - Skips execution when only documentation files are changed (files in the `documentation/` directory or any Markdown files)

2. **Main Branch Build Workflow**
   - Runs automatically when changes are merged to the main branch
   - Performs the same validation checks as the PR workflow
   - Builds and pushes the Docker image to DockerHub
   - Skips execution when only documentation files are changed (files in the `documentation/` directory or any Markdown files)

### Setting Up GitHub Secrets and Variables

To enable the Docker image publishing and application configuration, you need to configure:

1. In your GitHub repository settings under "Secrets and variables" > "Actions":

   **Secrets (for sensitive information):**
   - Add the secret: `DOCKERHUB_TOKEN` (your DockerHub Personal Access Token)
   - Add the secret: `ADMIN_PASSWORD` (bcrypt hashed password for admin user)
   - Add the secret: `ROUTER_PASSWORD` (password for the Peplink router)

   **Variables (for non-sensitive information):**
   - Add the variable: `DOCKERHUB_USERNAME` (your DockerHub username)
   - Add the variable: `ROUTER_IP` (IP address of the Peplink router)
   - Add the variable: `ROUTER_USERID` (user ID for the Peplink router, typically "admin")

To create a DockerHub Personal Access Token:
1. Log in to [Docker Hub](https://hub.docker.com)
2. Go to Account Settings > Security
3. Create a new access token with appropriate permissions
4. Copy the token value (you won't be able to see it again)

For the `ADMIN_PASSWORD` secret:

1. Store your plain password in the `ADMIN_PASSWORD` GitHub secret
2. The GitHub Actions workflow will automatically hash it during the build process using bcrypt
3. This ensures the password is properly formatted for the web app's login system

## Manual Deployment

If you need to deploy manually, follow these steps:

### Prerequisites

1. **Docker Hub Account:**

   - Ensure you have a PAT (Personal Access Token) from Docker Hub for the [HurtecDev](https://hub.docker.com/u/hurtecdev) repo.
   - Ensure your system supports multi-platform builds:
     ```sh
     docker buildx create --use --name multi-platform-builder
     docker buildx inspect --bootstrap
     ```

### Local Steps

1. Login to docker CLI with `docker login -u hurtecdev`
2. Enter password from PAT
3. If making changes to the mosquitto container:
   1. `docker buildx build --platform linux/arm/v7,linux/arm64,linux/amd64 --push -t hurtecdev/sensible-defaults-eclipse-mosquitto:latest -f Dockerfile.mosquitto .`
4. If making changes to the main code (we only need linux/arm64 for the current routers):
   1. `docker buildx build --platform linux/arm64 --push -t hurtecdev/hurtec-dev:latest -f Dockerfile.combined-arm .`

## Router Steps

Pull latest images.

1. Remote web admin into the router and go to Advanced > Docker (E.g. https://???.peplink.com/cgi-bin/MANGA/index.cgi?mode=config&option=docker)
2. If you need to update the mosquitto one (rare, only needed first time on router most likely)
   - Press `Click here to search and download Docker images`
   - Search for `hurtecdev/sensible-defaults-eclipse-mosquitto` and download it
   - Search for `postgres` and download it
3. Press `Click here to pull Docker image.`
4. Enter the image name (e.g. `hurtecdev/hurtec-dev`), username `hurtecdev` and password (from PAT)

### Mosquitto

We use a custom mosquitto image because the default `eclipse-mosquitto` image doesn't support providing config via environment variables or CLI, so we can't set defaults to get it working.

If separate vlan, do "--network vlan1"

```sh
docker run --ip=192.168.82.5 --name mosquitto -p 1883:1883 hurtecdev/sensible-defaults-eclipse-mosquitto
```

### Postgres

```sh
docker run --ip=192.168.82.6 --name postgres -p 5432:5432 -e POSTGRES_USER=hurtec -e POSTGRES_PASSWORD=hurtec -e POSTGRES_DB=hurtec postgres
```

### Combined App

```sh
docker run --ip=192.168.82.7 --name hurtec_combined_app -p 8088:8088 -e MQTT_BROKER_ADDRESS=192.168.82.5 -e DATABASE_URL=postgresql://hurtec:hurtec@192.168.82.6/hurtec hurtecdev/hurtec-dev
```

# EventCatalog Documentation

This repository includes an [EventCatalog](https://www.eventcatalog.dev/) project in the `documentation` directory that documents our event-driven architecture.

## Local Development

To work on the EventCatalog documentation locally:

1. Navigate to the documentation directory:
   ```sh
   cd documentation
   ```

2. Install dependencies:
   ```sh
   npm install
   ```

3. Start the development server:
   ```sh
   npm run dev
   ```

4. Open your browser and go to `http://localhost:3000` to view the documentation.

## Building for Production

To build the documentation for production:

```sh
cd documentation
npm run build
```

The built files will be in the `documentation/dist` directory. These can be served using any static file hosting service if needed.

# Development Tips

## AI Coding Tools

If you use an AI coding tool like cursor to GitHub Copilot, you should create a custom settings file to tell it to use the correct python environment and to use the correct linter and formatter.

We ignore these files from source control as they may be specific to the user, but if you have useful tips for what to add, include them here in the README.md file.

### Cursor

```json
{
    "environment": {
        "conda": {
            "environment": "integration",
            "activateCommand": "./.venv/Scripts/activate"
        },
        "shell": "powershell"
    },
    "codeQuality": {
        "typeChecking": {
            "tool": "mypy",
            "enabled": true
        },
        "linting": {
            "tool": "pylint",
            "enabled": true
        }
    },
    "editor": {
        "formatOnSave": true,
        "defaultFormatter": "black"
    }
}

```

### GitHub Copilot

Create a `.vscode/settings.json` file with the following configuration. Adjust the `python.defaultInterpreterPath` based on your environment setup (conda, venv, or uv's .venv).

```json
{
    // Example for Conda:
    // "python.defaultInterpreterPath": "C:\\Users\\YourUser\\anaconda3\\envs\\integration\\python.exe",
    // "python.condaPath": "C:\\Users\\YourUser\\anaconda3\\Scripts\\conda.exe",

    // Example for venv/uv:
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe", // Windows
    // "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python", // Linux/macOS

    "python.analysis.typeCheckingMode": "basic", // Or "strict"
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": true,
    "python.formatting.provider": "black",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
        "source.organizeImports": "explicit"
    },
    "[python]": {
        "editor.defaultFormatter": "ms-python.black-formatter",
        "editor.formatOnSave": true
    },
    "mypy-type-checker.args": [
        "--config-file=../pyproject.toml" // Assuming pyproject.toml is in the root
    ],
    "pylint.args": [
        "--rcfile=../pyproject.toml" // Assuming pyproject.toml is in the root
    ],
    "github.copilot.enable": {
        "*": true
    },
    "github.copilot.advanced": {} // Keep default advanced settings unless needed
}
```

This configuration:
-   Sets up Python interpreter path (adjust as needed for your setup)
-   Enables type checking (mypy extension recommended)
-   Enables linting with pylint (pylint extension recommended)
-   Uses Black as the formatter (black formatter extension recommended)
-   Enables format on save
-   Configures GitHub Copilot
-   Enables automatic import organization
-   Points linters/type checkers to configuration in `pyproject.toml` (assuming it exists at the root)

# Architecture

The Dockerized Web App with MQTT Broker and Background Task as custom code running via `main.py` in a single container (due to peplink not allowing docker networks - the original design had them separated).

Separateley there is a mosquitto broker running to support MQTT nessages.

## Data Flows

The main data flows are as follows:

#### GPS from Router to AWS

```mermaid
sequenceDiagram
   participant background_task
   participant router
   participant mosquitto
   participant mqtt_broker
   participant AWS_IoT

   background_task->>router: Get GPS Data
   router->>background_task: Return GPS Data
   background_task->>mosquitto: Publish "out/gps"
   mosquitto->>mqtt_broker: Subscribe to "out/..."
   mqtt_broker->>AWS_IoT: Send Message to <br/> {env}/{tenant_name}/{device_name}/out/gps
```

#### Device Data from PLC to AWS

```mermaid
sequenceDiagram
   participant PLC
   participant Sensors_BMS_Etc
   participant mosquitto
   participant mqtt_broker
   participant AWS_IoT

   PLC->>Sensors_BMS_Etc: Get Device Data
   Sensors_BMS_Etc->>PLC: Return Device Data
   PLC->>mosquitto: Publish "out/device"
   mosquitto->>mqtt_broker: Subscribe to "out/..."
   mqtt_broker->>AWS_IoT: Send Message to <br/> {env}/{tenant_name}/{device_name}/out/device
```
