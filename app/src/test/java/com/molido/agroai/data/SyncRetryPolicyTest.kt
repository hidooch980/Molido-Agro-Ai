package com.molido.agroai.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test

class SyncRetryPolicyTest {
    @Test fun retryDelayStartsAtThirtySecondsAndDoubles() {
        val now = 1_000_000L
        assertEquals(now + 30_000L, SyncRetryPolicy.nextAttemptAt(now, 0))
        assertEquals(now + 60_000L, SyncRetryPolicy.nextAttemptAt(now, 1))
        assertEquals(now + 120_000L, SyncRetryPolicy.nextAttemptAt(now, 2))
    }

    @Test fun retryDelayIsCappedAtSixHours() {
        val now = 1_000_000L
        assertEquals(now + 6L * 60L * 60L * 1000L, SyncRetryPolicy.nextAttemptAt(now, 100))
    }

    @Test fun retryTimestampSaturatesInsteadOfOverflowing() {\n        assertEquals(Long.MAX_VALUE, SyncRetryPolicy.nextAttemptAt(Long.MAX_VALUE - 10L, 0))\n    }\n\n    @Test fun negativeAttemptCountIsRejected() {\n        assertThrows(IllegalArgumentException::class.java) { SyncRetryPolicy.nextAttemptAt(0L, -1) }\n    }\n\n    @Test fun retryDelayNeverGoesBackwards() {
        val now = 1_000_000L
        assertTrue(SyncRetryPolicy.nextAttemptAt(now, 0) > now)
    }
}
