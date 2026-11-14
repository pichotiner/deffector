package ru.kst.deffector

import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min

object ArTiming {
    const val DETECT_INTERVAL_MS = 700L
    const val MISSING_HOLD_MS = 900L
    const val FADE_MS = 500L
    const val STALE_MS = 3000L
}

data class DetectionTrack(
    val key: Long,
    val detection: Detection,
    val box: List<Double>,
    val seen: Long,
    val width: Int,
    val height: Int,
    val missingSince: Long? = null,
    val visible: Boolean = true
)

/** Стабилизирует только отображение. Для анализа остаётся исходная рамка детектора. */
class DetectionTracker {
    private var nextKey = 0L
    private var tracks = emptyList<DetectionTrack>()

    fun update(detections: List<Detection>, now: Long, width: Int, height: Int): List<DetectionTrack> {
        advance(now)
        val incoming = detections.filter { d ->
            runCatching { normalizedBox(d.bbox).let { it[2] > it[0] && it[3] > it[1] } }.getOrDefault(false)
        }
        // Сначала лучшие пространственные пары: перестановка ответа не меняет идентичность узлов.
        val pairs = tracks.flatMapIndexed { oldIndex, old ->
            incoming.mapIndexedNotNull { newIndex, d ->
                if (old.width != width || old.height != height || old.detection.cv_class != d.cv_class ||
                    old.detection.component_id != d.component_id || old.detection.match != d.match ||
                    old.detection.candidates.orEmpty().toSet() != d.candidates.orEmpty().toSet()) null
                else score(old.detection.bbox, d.bbox)?.let { Triple(oldIndex, newIndex, it) }
            }
        }.sortedByDescending { it.third }
        val matches = mutableMapOf<Int, Int>()
        val used = mutableSetOf<Int>()
        pairs.forEach { (oldIndex, newIndex, _) ->
            if (oldIndex !in matches && newIndex !in used) { matches[oldIndex] = newIndex; used += newIndex }
        }
        val updated = tracks.mapIndexed { oldIndex, old ->
            matches[oldIndex]?.let { index ->
                val d = incoming[index]
                val motion = old.box.zip(d.bbox).maxOf { abs(it.first - it.second) }
                val box = when {
                    motion < .008 -> old.box // Мелкий шум не заставляет рамку дрожать.
                    motion > .10 -> d.bbox // При движении камеры рамка быстро догоняет объект.
                    else -> old.box.zip(d.bbox) { a, b -> a + (b - a) * .55 }
                }
                old.copy(detection = d, box = box, seen = now, missingSince = null, visible = true)
            } ?: old.copy(missingSince = old.missingSince ?: now)
        }
        tracks = updated + incoming.mapIndexedNotNull { index, d ->
            if (index in used) null else DetectionTrack(nextKey++, d, d.bbox, now, width, height)
        }
        return advance(now)
    }

    fun advance(now: Long): List<DetectionTrack> {
        tracks = tracks.mapNotNull { track ->
            val fadeAt = min(track.seen + ArTiming.STALE_MS, track.missingSince?.plus(ArTiming.MISSING_HOLD_MS) ?: Long.MAX_VALUE)
            if (now >= fadeAt + ArTiming.FADE_MS) null else track.copy(visible = now < fadeAt)
        }
        return tracks
    }

    private fun score(a: List<Double>, b: List<Double>): Double? {
        val aa = normalizedBox(a); val bb = normalizedBox(b)
        val intersection = max(0.0, min(aa[2], bb[2]) - max(aa[0], bb[0])) * max(0.0, min(aa[3], bb[3]) - max(aa[1], bb[1]))
        val union = (aa[2] - aa[0]) * (aa[3] - aa[1]) + (bb[2] - bb[0]) * (bb[3] - bb[1]) - intersection
        val overlap = if (union > 0) intersection / union else 0.0
        val distance = hypot((aa[0] + aa[2] - bb[0] - bb[2]) / 2, (aa[1] + aa[3] - bb[1] - bb[3]) / 2)
        return if (overlap >= .12 || distance < .10) overlap + 1 - distance else null
    }
}
