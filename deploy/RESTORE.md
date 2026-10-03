# Restoring the clinic database

Backups come from `deploy/backup.sh` (nightly, `/var/backups/hms`, 14 days). Each run writes
`db-<UTC time>.dump` (Postgres custom format) and `media-<UTC time>.tar.gz` (uploaded photos/guides).

## Full restore (server lost or data damaged)

1. Stop writes: `pm2 stop avocado-api` (nginx now shows the "call reception" page).
2. Pick the newest good dump: `ls -lt /var/backups/hms`.
3. Restore into a fresh database, then switch over:
   ```bash
   createdb avocado_restore
   pg_restore --no-owner --dbname=postgresql://USER:PASS@localhost/avocado_restore /var/backups/hms/db-STAMP.dump
   ```
   Point `DATABASE_URL` in `/var/www/hms-backend/.env` at `avocado_restore` (or rename databases).
4. Media: `tar -xzf /var/backups/hms/media-STAMP.tar.gz -C /var/www/hms-backend/uploads`.
5. Bring schema to the deployed code: `cd /var/www/hms-backend && .venv/bin/alembic upgrade head`.
6. Start: `pm2 start avocado-api`, then check `curl -s localhost:8004/api/health/ready`.
7. Bookings made after the backup time are lost from the system. Ask reception to check WhatsApp
   chats and the activity log export from that day before reopening online booking.

## Practise it

Restore the latest dump into a scratch database once a month (step 3 only) and compare
`select count(*) from appointments` with production. An untested backup is not a backup.
