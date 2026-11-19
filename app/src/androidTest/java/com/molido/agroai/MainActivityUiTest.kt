package com.molido.agroai

import androidx.compose.ui.test.assertExists
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test

class MainActivityUiTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    @Test
    fun dashboardAndNavigationRenderInPersian() {
        composeRule.onNodeWithText("مولیدو آگرو").assertExists()
        composeRule.onNodeWithText("خانه").assertExists()
        composeRule.onNodeWithText("گلخانه").assertExists()
        composeRule.onNodeWithText("مدیریت هوشمند کشاورزی و گلخانه").assertExists()
    }
}
