module.exports = {
  apps: [
    {
      name: "avocado-api",
      script: "./start-api.sh",
      cwd: "/var/www/hms-backend",
      interpreter: "bash",
      autorestart: true,
      min_uptime: 20000,
      max_restarts: 15,
      restart_delay: 5000,
      exp_backoff_restart_delay: 200,
      kill_timeout: 8000,
      max_memory_restart: "400M",
    },
  ],
};
