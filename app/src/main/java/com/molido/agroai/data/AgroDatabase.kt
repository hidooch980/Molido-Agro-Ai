package com.molido.agroai.data

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        CropObservationEntity::class,
        GreenhouseEntity::class,
        CropCycleEntity::class,
        FarmActivityEntity::class,
        InventoryItemEntity::class,
        FinancialEntryEntity::class,
        SyncOperationEntity::class,
        AppMetadataEntity::class,
        SyncInboxEntity::class
    ],
    version = 5,
    exportSchema = false
)
abstract class AgroDatabase : RoomDatabase() {
    abstract fun cropObservationDao(): CropObservationDao
    abstract fun greenhouseDao(): GreenhouseDao
    abstract fun cropCycleDao(): CropCycleDao
    abstract fun farmActivityDao(): FarmActivityDao
    abstract fun inventoryDao(): InventoryDao
    abstract fun financeDao(): FinanceDao
    abstract fun syncOperationDao(): SyncOperationDao
    abstract fun appMetadataDao(): AppMetadataDao
    abstract fun syncInboxDao(): SyncInboxDao

    companion object {


        val MIGRATION_3_4: Migration = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS app_metadata (key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(key))")
            }
        }

        val MIGRATION_4_5: Migration = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS sync_inbox (id TEXT NOT NULL, entityType TEXT NOT NULL, entityId TEXT NOT NULL, encryptedPayload TEXT NOT NULL, serverVersion INTEGER NOT NULL, updatedAtEpochMillis INTEGER NOT NULL, deleted INTEGER NOT NULL, state TEXT NOT NULL, PRIMARY KEY(id))")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_sync_inbox_entityType_entityId_serverVersion ON sync_inbox(entityType, entityId, serverVersion)")
            }
        }

        val MIGRATION_2_3: Migration = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS sync_operations (id TEXT NOT NULL, idempotencyKey TEXT NOT NULL, entityType TEXT NOT NULL, entityId TEXT NOT NULL, operation TEXT NOT NULL, payloadJson TEXT NOT NULL, state TEXT NOT NULL, attemptCount INTEGER NOT NULL, createdAtEpochMillis INTEGER NOT NULL, nextAttemptAtEpochMillis INTEGER NOT NULL, lastError TEXT, PRIMARY KEY(id))")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_sync_operations_idempotencyKey ON sync_operations(idempotencyKey)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_sync_operations_state_nextAttemptAtEpochMillis ON sync_operations(state, nextAttemptAtEpochMillis)")
            }
        }

        val MIGRATION_1_2: Migration = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS greenhouses (id TEXT NOT NULL, name TEXT NOT NULL, areaSquareMeters REAL NOT NULL, location TEXT NOT NULL, cultivationMethod TEXT NOT NULL, createdAtEpochMillis INTEGER NOT NULL, isActive INTEGER NOT NULL, PRIMARY KEY(id))")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_greenhouses_name ON greenhouses(name)")
                db.execSQL("CREATE TABLE IF NOT EXISTS crop_cycles (id TEXT NOT NULL, greenhouseId TEXT NOT NULL, cropCode TEXT NOT NULL, startDateEpochMillis INTEGER NOT NULL, expectedHarvestDateEpochMillis INTEGER, plantedAreaSquareMeters REAL NOT NULL, plantCount INTEGER, status TEXT NOT NULL, notes TEXT NOT NULL, PRIMARY KEY(id))")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_crop_cycles_greenhouseId ON crop_cycles(greenhouseId)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_crop_cycles_cropCode ON crop_cycles(cropCode)")
                db.execSQL("CREATE TABLE IF NOT EXISTS farm_activities (id TEXT NOT NULL, greenhouseId TEXT, cropCycleId TEXT, cropCode TEXT, type TEXT NOT NULL, title TEXT NOT NULL, quantity REAL, unit TEXT, cost REAL, occurredAtEpochMillis INTEGER NOT NULL, notes TEXT NOT NULL, syncState TEXT NOT NULL, PRIMARY KEY(id))")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_farm_activities_greenhouseId ON farm_activities(greenhouseId)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_farm_activities_cropCycleId ON farm_activities(cropCycleId)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_farm_activities_type ON farm_activities(type)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_farm_activities_occurredAtEpochMillis ON farm_activities(occurredAtEpochMillis)")
                db.execSQL("CREATE TABLE IF NOT EXISTS inventory_items (id TEXT NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL, quantity REAL NOT NULL, unit TEXT NOT NULL, minimumQuantity REAL NOT NULL, updatedAtEpochMillis INTEGER NOT NULL, PRIMARY KEY(id))")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_inventory_items_name ON inventory_items(name)")
                db.execSQL("CREATE TABLE IF NOT EXISTS financial_entries (id TEXT NOT NULL, greenhouseId TEXT, type TEXT NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL, currency TEXT NOT NULL, occurredAtEpochMillis INTEGER NOT NULL, description TEXT NOT NULL, PRIMARY KEY(id))")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_financial_entries_occurredAtEpochMillis ON financial_entries(occurredAtEpochMillis)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_financial_entries_greenhouseId ON financial_entries(greenhouseId)")
            }
        }
    }
}
