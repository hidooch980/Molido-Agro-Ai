package com.molido.agroai.data

import android.content.Context
import androidx.room.Room

object AgroDatabaseProvider {
    @Volatile
    private var instance: AgroDatabase? = null

    fun get(context: Context): AgroDatabase =
        instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                AgroDatabase::class.java,
                "molido_agro_local.db"
            ).openHelperFactory(DatabaseEncryption.factory(context))
                .addMigrations(AgroDatabase.MIGRATION_1_2, AgroDatabase.MIGRATION_2_3, AgroDatabase.MIGRATION_3_4, AgroDatabase.MIGRATION_4_5, AgroDatabase.MIGRATION_5_6, AgroDatabase.MIGRATION_6_7)
                .build()
                .also { instance = it }
        }
}
