
import { defineConfig } from '@playwright/test';
export default defineConfig({
  timeout: 120000,
  use: { baseURL: 'http://localhost:5173' }
});
