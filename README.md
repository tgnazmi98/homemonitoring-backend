# Home Monitoring Backend

Django REST API and Python data logger for electrical monitoring. This system collects real-time data from SDM230 Modbus energy meters and exposes it via REST API and WebSocket endpoints.

## Tech Stack

### Backend API
- **Framework:** Django 5.2 + Django REST Framework
- **WebSocket:** Django Channels 4.0 + Daphne
- **Database:** TimescaleDB (PostgreSQL extension)
- **Authentication:** JWT (djangorestframework-simplejwt)
- **CORS:** django-cors-headers

### Data Logger
- **Protocol:** Modbus TCP (pymodbus)
- **Supported Meters:** SDM230, SDM630 (configurable)
- **Data Collection:** Continuous polling with API submission

## Features

### API
- **Meter Management:** CRUD operations for energy meters
- **Power Readings:** Real-time voltage, current, power, frequency data
- **Energy Readings:** Historical energy consumption data
- **Data Export:** CSV and Excel export endpoints
- **WebSocket:** Real-time data streaming to connected clients
- **Health Checks:** Endpoint for container orchestration

### Logger
- **Modbus Communication:** Read registers from SDM energy meters
- **Multi-meter Support:** Configure multiple meters on RS485 bus
- **Local Buffering:** SQLite fallback when API is unavailable
- **Configurable Parameters:** Select which registers to poll

## Project Structure

```
backend/
├── electrical_monitoring/    # Django project settings
│   ├── settings.py          # Main configuration
│   ├── urls.py              # URL routing
│   ├── asgi.py              # ASGI config (WebSocket)
│   └── wsgi.py              # WSGI config
├── meters/                   # Main Django app
│   ├── models.py            # Meter, PowerReading, EnergyReading
│   ├── views.py             # API endpoints
│   ├── serializers.py       # DRF serializers
│   ├── consumers.py         # WebSocket consumers
│   ├── routing.py           # WebSocket routing
│   └── management/commands/ # Custom management commands
├── Dockerfile
├── manage.py
└── requirements.txt

logger/
├── loggerpcv01.py           # Main logger application
├── modbus.py                # Modbus TCP communication
├── api_client.py            # Backend API client
├── db_manager.py            # SQLite buffer management
├── meterlist.json           # Meter register definitions
├── setting.json.example     # Configuration template
├── Dockerfile
└── requirements.txt
```

## API Endpoints

### Authentication
- `POST /api/token/` - Obtain JWT token pair
- `POST /api/token/refresh/` - Refresh access token

### Meters
- `GET /api/meters/` - List all meters
- `POST /api/meters/` - Create meter
- `GET /api/meters/{id}/` - Get meter details
- `PUT /api/meters/{id}/` - Update meter
- `DELETE /api/meters/{id}/` - Delete meter

### Readings
- `POST /api/meters/{id}/power/` - Submit power reading
- `GET /api/meters/{id}/power/latest/` - Get latest power reading
- `GET /api/meters/{id}/power/history/` - Get historical readings
- `POST /api/meters/{id}/energy/` - Submit energy reading
- `GET /api/meters/{id}/energy/latest/` - Get latest energy reading
- `GET /api/export/` - Export data (CSV/Excel)

### WebSocket
- `ws://host/ws/meters/` - Real-time meter data stream

### Health
- `GET /health/` - Health check endpoint

## Setup

### Prerequisites

- Python 3.11+
- TimescaleDB or PostgreSQL
- Running energy meter on Modbus TCP

### Backend Installation

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DEBUG=1
export SECRET_KEY=your-secret-key
export DB_HOST=localhost
export DB_NAME=electrical_monitoring
export DB_USER=your_user
export DB_PASSWORD=your_password

# Run migrations
python manage.py migrate
python manage.py setup_timescaledb

# Create superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver
# Or with WebSocket support:
daphne -b 0.0.0.0 -p 8000 electrical_monitoring.asgi:application
```

### Logger Installation

```bash
cd logger

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure settings
cp setting.json.example setting.json
# Edit setting.json with your meter IP and parameters

# Run logger
python loggerpcv01.py
```

## Configuration

### Logger Settings (setting.json)

```json
{
  "Logger_ID": "Home",
  "Device_IP": "192.168.1.100",
  "Device_Port": 502,
  "Troubleshoot": 0,
  "meter_params": "meterlist.json",
  "meterlist": [
    {
      "name": "Main",
      "id": 1,
      "model": "sdm230",
      "paramlist": ["Voltage", "Current", "Active Power", ...]
    }
  ]
}
```

### Environment Variables (Backend)

```env
DEBUG=0
SECRET_KEY=your-django-secret-key
ALLOWED_HOSTS=localhost,your-domain.com
DB_HOST=timescaledb
DB_NAME=electrical_monitoring
DB_USER=your_user
DB_PASSWORD=your_password
CORS_ALLOWED_ORIGINS=https://your-frontend.com
JWT_ACCESS_TOKEN_LIFETIME=60
JWT_REFRESH_TOKEN_LIFETIME=10080
```

## Docker

```bash
# Build and run backend
docker build -t homemonitoring-backend ./backend
docker run -p 8000:8000 homemonitoring-backend

# Build and run logger
docker build -t homemonitoring-logger ./logger
docker run homemonitoring-logger
```

## Related Repositories

- [homemonitoring-frontend](https://github.com/yourusername/homemonitoring-frontend) - Next.js Dashboard
- [personal-infrastructure](https://github.com/yourusername/personal-infrastructure) - Docker & Traefik Configuration

## License

MIT
