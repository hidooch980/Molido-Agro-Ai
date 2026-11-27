package com.molido.agroai.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/**
 * CRM leads/activities and the harvest postings that connect a crop cycle to ERP stock. Everything
 * here is account-scoped on the server; the local database stays the offline source of truth for the
 * field records the sync engine already owns.
 */
object CrmApi {
    val leadStages = listOf("NEW", "QUALIFIED", "PROPOSAL", "WON", "LOST")
    val activityTypes = listOf("CALL", "EMAIL", "MEETING", "TASK", "NOTE", "VISIT")

    data class Lead(
        val id: String,
        val title: String,
        val stage: String,
        val estimatedValue: Double,
        val currency: String,
        val notes: String,
    )

    data class Activity(
        val id: String,
        val subject: String,
        val activityType: String,
        val state: String,
        val leadId: String?,
    )

    data class Product(val id: String, val sku: String, val name: String, val unit: String)

    data class Harvest(
        val id: String,
        val greenhouseId: String,
        val productId: String,
        val warehouseId: String,
        val quantity: Double,
        val unitPrice: Double,
        val unit: String,
    )

    suspend fun leads(context: Context): List<Lead> = withContext(Dispatchers.IO) {
        val items = items(ServerHttp.request(context, "GET", "/v1/crm/leads"))
        buildList {
            for (index in 0 until items.length()) {
                val row = items.optJSONObject(index) ?: continue
                add(
                    Lead(
                        id = row.optString("id"),
                        title = row.optString("title"),
                        stage = row.optString("stage", "NEW"),
                        estimatedValue = row.optDouble("estimatedValue", 0.0),
                        currency = row.optString("currency", "IRR"),
                        notes = row.optString("notes"),
                    )
                )
            }
        }
    }

    suspend fun createLead(
        context: Context,
        title: String,
        estimatedValue: Double,
        stage: String = "NEW",
        notes: String = "",
    ): Lead = withContext(Dispatchers.IO) {
        require(title.trim().length >= 2) { "عنوان سرنخ باید حداقل ۲ نویسه باشد." }
        val body = JSONObject()
            .put("title", title.trim())
            .put("estimatedValue", estimatedValue)
            .put("stage", stage)
            .put("notes", notes.trim())
            .toString()
        val row = JSONObject(ServerHttp.request(context, "POST", "/v1/crm/leads", body))
        Lead(
            id = row.optString("id"),
            title = row.optString("title", title.trim()),
            stage = row.optString("stage", stage),
            estimatedValue = row.optDouble("estimatedValue", estimatedValue),
            currency = row.optString("currency", "IRR"),
            notes = row.optString("notes", notes.trim()),
        )
    }

    suspend fun moveLead(context: Context, leadId: String, stage: String): String = withContext(Dispatchers.IO) {
        require(leadId.isNotBlank()) { "سرنخ انتخاب نشده است." }
        require(stage in leadStages) { "مرحله سرنخ نامعتبر است." }
        val body = JSONObject().put("stage", stage).toString()
        JSONObject(ServerHttp.request(context, "POST", "/v1/crm/leads/$leadId/stage", body))
            .optString("stage", stage)
    }

    suspend fun activities(context: Context): List<Activity> = withContext(Dispatchers.IO) {
        val items = items(ServerHttp.request(context, "GET", "/v1/crm/activities"))
        buildList {
            for (index in 0 until items.length()) {
                val row = items.optJSONObject(index) ?: continue
                add(
                    Activity(
                        id = row.optString("id"),
                        subject = row.optString("subject"),
                        activityType = row.optString("activityType", "TASK"),
                        state = row.optString("state", "OPEN"),
                        leadId = row.optString("leadId").takeIf { it.isNotBlank() },
                    )
                )
            }
        }
    }

    suspend fun createActivity(
        context: Context,
        activityType: String,
        subject: String,
        leadId: String?,
        description: String = "",
    ): Activity = withContext(Dispatchers.IO) {
        require(subject.trim().length >= 2) { "موضوع فعالیت باید حداقل ۲ نویسه باشد." }
        require(activityType in activityTypes) { "نوع فعالیت نامعتبر است." }
        require(!leadId.isNullOrBlank()) { "هر فعالیت باید به یک سرنخ یا مشتری وصل شود." }
        val body = JSONObject()
            .put("activityType", activityType)
            .put("subject", subject.trim())
            .put("leadId", leadId)
            .put("description", description.trim())
            .toString()
        val row = JSONObject(ServerHttp.request(context, "POST", "/v1/crm/activities", body))
        Activity(
            id = row.optString("id"),
            subject = row.optString("subject", subject.trim()),
            activityType = row.optString("activityType", activityType),
            state = row.optString("state", "OPEN"),
            leadId = leadId,
        )
    }

    suspend fun products(context: Context): List<Product> = withContext(Dispatchers.IO) {
        val items = items(ServerHttp.request(context, "GET", "/v1/erp/products?limit=200"))
        buildList {
            for (index in 0 until items.length()) {
                val row = items.optJSONObject(index) ?: continue
                add(
                    Product(
                        id = row.optString("id"),
                        sku = row.optString("sku"),
                        name = row.optString("name"),
                        unit = row.optString("unit", "kg"),
                    )
                )
            }
        }
    }

    suspend fun recordHarvest(
        context: Context,
        greenhouseId: String,
        cropCycleId: String,
        productId: String,
        warehouseId: String,
        quantity: Double,
        unitPrice: Double,
        unit: String,
        idempotencyKey: String,
    ): Harvest = withContext(Dispatchers.IO) {
        require(greenhouseId.isNotBlank() && cropCycleId.isNotBlank()) { "گلخانه و دوره کشت را انتخاب کنید." }
        require(productId.isNotBlank()) { "محصول را انتخاب کنید." }
        require(warehouseId.isNotBlank()) { "انبار مقصد را وارد کنید." }
        require(quantity > 0) { "مقدار برداشت باید بزرگ‌تر از صفر باشد." }
        val body = JSONObject()
            .put("idempotencyKey", idempotencyKey)
            .put("greenhouseId", greenhouseId)
            .put("cropCycleId", cropCycleId)
            .put("productId", productId)
            .put("warehouseId", warehouseId.trim())
            .put("quantity", quantity)
            .put("unitPrice", unitPrice)
            .put("unit", unit)
            .toString()
        val row = JSONObject(ServerHttp.request(context, "POST", "/v1/erp/harvest", body))
        Harvest(
            id = row.optString("id"),
            greenhouseId = greenhouseId,
            productId = productId,
            warehouseId = warehouseId.trim(),
            quantity = row.optDouble("quantity", quantity),
            unitPrice = row.optDouble("unitPrice", unitPrice),
            unit = unit,
        )
    }

    private fun items(response: String): JSONArray =
        JSONObject(response).optJSONArray("items") ?: JSONArray()
}