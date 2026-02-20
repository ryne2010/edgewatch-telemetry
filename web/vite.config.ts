import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite dev server proxy (host dev lane):
// - UI runs on http://localhost:5173 (`make web-dev`)
// - API runs on http://localhost:8080 (`make api-dev`)
//
// Note: the Docker Compose lane exposes the containerized API/UI on http://localhost:8082.
//
// The UI code uses relative fetches (e.g. /api/v1/devices), so we proxy those
// paths in dev to keep local dev friction low.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
      '/readyz': 'http://localhost:8080',
    },
  },
})
