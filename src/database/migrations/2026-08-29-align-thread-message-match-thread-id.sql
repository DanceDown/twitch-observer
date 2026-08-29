-- Align thread_message_match.thread_id with thread.thread_id.
-- Existing values are safe to cast because the foreign key points at thread.thread_id,
-- which is an INTEGER/SERIAL column.

DO $migration$
DECLARE
    fk_name TEXT;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'thread_message_match'
          AND column_name = 'thread_id'
          AND udt_name = 'int8'
    ) THEN
        SELECT tc.constraint_name
        INTO fk_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = current_schema()
          AND tc.table_name = 'thread_message_match'
          AND tc.constraint_type = 'FOREIGN KEY'
          AND kcu.column_name = 'thread_id'
        LIMIT 1;

        IF fk_name IS NOT NULL THEN
            EXECUTE format('ALTER TABLE thread_message_match DROP CONSTRAINT %I', fk_name);
        END IF;

        ALTER TABLE thread_message_match
            ALTER COLUMN thread_id TYPE INTEGER USING thread_id::INTEGER;

        ALTER TABLE thread_message_match
            ADD CONSTRAINT thread_message_match_thread_id_fkey
            FOREIGN KEY (thread_id)
            REFERENCES thread(thread_id)
            ON DELETE CASCADE;
    END IF;
END
$migration$;
