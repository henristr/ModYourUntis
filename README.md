# ModYourUntis

## Configuration with .env

Create a `.env` file in the project root to configure the app.

Example:

```env
SECRET_KEY=your-key
SCHOOL=YourSchool
SERVER=your-school.webuntis.com

APP_HOST=0.0.0.0
APP_PORT=5000
APP_DEBUG=true
```

The app reads `.env` automatically on startup. If a variable is missing, a default is used.

## Data Storage

Visual settings (themes and lesson styles) are stored in `modyouruntis.json` in the project root.
