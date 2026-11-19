package com.molido.agroai.data

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(entities = [CropObservationEntity::class], version = 1, exportSchema = false)
abstract class AgroDatabase : RoomDatabase() {
    abstract fun cropObservationDao(): CropObservationDao
}
