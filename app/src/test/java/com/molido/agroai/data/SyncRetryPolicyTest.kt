package com.molido.agroai.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
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

    @Test fun retryDelayNeverGoesBackwards() {
        val now = 1_000_000L
        assertTrue(SyncRetryPolicy.nextAttemptAt(now, 0) > now)
    }
}
