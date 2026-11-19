package com.molido.agroai

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalLayoutDirection

private val Forest = Color(0xFF123C2B)
private val Leaf = Color(0xFF2E8B57)
private val SurfaceDark = Color(0xFF17231D)
private val Muted = Color(0xFFB8C8BE)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(
                primary = Leaf,
                background = Forest,
                surface = SurfaceDark,
                onPrimary = Color.White,
                onBackground = Color.White,
                onSurface = Color.White
            )) {
                Surface(modifier = Modifier.fillMaxSize(), color = Forest) {
                    CompositionRoot()
                }
            }
        }
    }
}

@Composable
private fun CompositionRoot() {
    androidx.compose.runtime.CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
        DashboardScreen()
    }
}

private data class Module(val title: String, val subtitle: String, val symbol: String)

private val modules = listOf(
    Module("پزشک هوشمند گیاه", "بررسی سلامت با تصویر", "🌿"),
    Module("مدیریت گلخانه", "گلخانه‌ها و دوره‌های کشت", "🏡"),
    Module("آبیاری", "ثبت و برنامه‌ریزی آب", "💧"),
    Module("تغذیه و کوددهی", "ثبت کود و برنامه غذایی", "🧪"),
    Module("آفات و بیماری‌ها", "پایش و سوابق سلامت", "🔬"),
    Module("برداشت و تولید", "عملکرد و کیفیت محصول", "🌱"),
    Module("انبار نهاده‌ها", "کود، بذر و ملزومات", "📦"),
    Module("گزارش مالی", "هزینه و درآمد", "📊")
)

@Composable
private fun DashboardScreen() {
    Column(
        modifier = Modifier.fillMaxSize().background(Forest).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.weight(1f)) {
                Text("مولیدو آگرو", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("دستیار هوشمند کشاورزی و گلخانه", color = Muted, style = MaterialTheme.typography.bodyMedium)
            }
            Text("🌾", style = MaterialTheme.typography.headlineLarge)
        }
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = SurfaceDark),
            shape = RoundedCornerShape(20.dp)
        ) {
            Column(Modifier.padding(18.dp)) {
                Text("سلام، به مولیدو آگرو خوش آمدید", fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(6.dp))
                Text("اطلاعات کشت خود را ثبت کنید تا دستیار کشاورزی بتواند به شما کمک کند.", color = Muted)
                Spacer(Modifier.height(12.dp))
                Text("وضعیت: نسخه پایه رابط کاربری", color = Color(0xFFFFD180), style = MaterialTheme.typography.labelMedium)
            }
        }
        Text("ابزارهای کشاورزی", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(bottom = 20.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            items(modules) { module ->
                ModuleCard(module)
            }
        }
    }
}

@Composable
private fun ModuleCard(module: Module) {
    Card(
        modifier = Modifier.fillMaxWidth().height(132.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceDark),
        shape = RoundedCornerShape(18.dp)
    ) {
        Column(
            modifier = Modifier.fillMaxSize().padding(14.dp),
            verticalArrangement = Arrangement.SpaceBetween
        ) {
            Text(module.symbol, style = MaterialTheme.typography.headlineMedium)
            Column {
                Text(module.title, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
                Text(module.subtitle, color = Muted, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
