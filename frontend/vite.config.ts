import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The frontend talks to the backend through an absolute base URL
// (see src/api.ts, VITE_API_BASE_URL), so no dev proxy is configured.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  preview: {
    port: 4173,
  },
});
