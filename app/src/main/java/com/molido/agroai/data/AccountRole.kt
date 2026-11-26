package com.molido.agroai.data

/**
 * Mirrors the server role that gates approvals (see `ROLES` in server/app.py). The app never
 * enforces anything the server does not, but it should tell the operator what to expect before a
 * request is refused.
 */
enum class AccountRole(val wire: String, val label: String) {
    OWNER("OWNER", "سرپرست"),
    OPERATOR("OPERATOR", "اپراتور"),
    ACCOUNTANT("ACCOUNTANT", "حسابدار");

    val canApproveFinances: Boolean get() = this == OWNER || this == ACCOUNTANT

    companion object {
        fun parse(value: String?): AccountRole? = entries.firstOrNull { it.wire == value?.trim() }
    }
}
