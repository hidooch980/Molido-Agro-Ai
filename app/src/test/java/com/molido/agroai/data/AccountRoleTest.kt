package com.molido.agroai.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AccountRoleTest {
    @Test
    fun parsesEveryServerRole() {
        assertEquals(AccountRole.OWNER, AccountRole.parse("OWNER"))
        assertEquals(AccountRole.OPERATOR, AccountRole.parse("OPERATOR"))
        assertEquals(AccountRole.ACCOUNTANT, AccountRole.parse("ACCOUNTANT"))
        assertEquals(AccountRole.OWNER, AccountRole.parse("  OWNER "))
    }

    @Test
    fun unknownOrMissingRoleStaysUnset() {
        assertNull(AccountRole.parse(null))
        assertNull(AccountRole.parse(""))
        assertNull(AccountRole.parse("SUPERUSER"))
    }

    @Test
    fun onlyOwnersAndAccountantsApproveFinances() {
        assertTrue(AccountRole.OWNER.canApproveFinances)
        assertTrue(AccountRole.ACCOUNTANT.canApproveFinances)
        assertFalse(AccountRole.OPERATOR.canApproveFinances)
    }
}
