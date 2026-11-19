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
        FinancialEntryEntity::class
    ],
    version = 2,
    exportSchema = false
)
abstract class AgroDatabase : RoomDatabase() {
    abstract fun cropObservationDao(): CropObservationDao
    abstract fun greenhouseDao(): GreenhouseDao
    abstract fun cropCycleDao(): CropCycleDao
    abstract fun farmActivityDao(): FarmActivityDao
    abstract fun inventoryDao(): InventoryDao
    abstract fun financeDao(): FinanceDao

    companion object {
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
