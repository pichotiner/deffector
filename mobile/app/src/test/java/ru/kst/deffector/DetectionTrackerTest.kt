package ru.kst.deffector

import org.junit.Assert.*
import org.junit.Test

class DetectionTrackerTest {
    private fun detection(x: Double, id: String? = null) = Detection(
        bbox = listOf(x, .2, .12, .18), cv_class = "valve", detection_confidence = .9,
        match = if (id == null) "not_in_card" else "matched", component_id = id,
        label = "Задвижка", attention_level = "check"
    )
    private fun DetectionTracker.updateAt(time: Long, vararg d: Detection) = update(d.toList(), time, 640, 480)

    @Test fun reorderedSameClassObjectsKeepIdentity() {
        val tracker = DetectionTracker()
        val first = tracker.updateAt(0, detection(.1), detection(.6))
        val second = tracker.updateAt(700, detection(.61), detection(.11))
        assertEquals(first.map { it.key }, second.map { it.key })
        assertEquals(.11, second[0].detection.bbox[0], .0001)
        assertEquals(.61, second[1].detection.bbox[0], .0001)
    }

    @Test fun smallJitterIsSuppressedButSourceAndStatusStayFresh() {
        val tracker = DetectionTracker()
        tracker.updateAt(0, detection(.1, "C-1"))
        val raw = detection(.104, "C-1").copy(attention_level = "defect", reason = "Новая причина")
        val track = tracker.updateAt(700, raw).single()
        assertEquals(.1, track.box[0], .0001)
        assertEquals(raw, track.detection)
        assertEquals("defect", track.detection.attention_level)
        assertEquals("Новая причина", track.detection.reason)
    }

    @Test fun moderateMovementIsSmoothedAndCropUsesOriginalBox() {
        val tracker = DetectionTracker()
        tracker.updateAt(0, detection(.1))
        val raw = detection(.15)
        val track = tracker.updateAt(700, raw).single()
        assertTrue(track.box[0] > .1 && track.box[0] < .15)
        assertEquals(raw.bbox, track.detection.bbox)
        assertArrayEquals(cropPixels(raw.bbox, 1280, 960), cropPixels(track.detection.bbox, 1280, 960))
    }

    @Test fun brieflyMissingObjectRecoversWithoutFadingOrChangingKey() {
        val tracker = DetectionTracker()
        val first = tracker.updateAt(0, detection(.1)).single()
        tracker.updateAt(700)
        assertTrue(tracker.advance(1400).single().visible)
        val recovered = tracker.updateAt(1400, detection(.11)).single()
        assertEquals(first.key, recovered.key)
        assertNull(recovered.missingSince)
        assertTrue(recovered.visible)
    }

    @Test fun missingObjectFadesThenIsRemoved() {
        val tracker = DetectionTracker()
        tracker.updateAt(0, detection(.1))
        tracker.updateAt(700)
        assertTrue(tracker.advance(1599).single().visible)
        assertFalse(tracker.advance(1600).single().visible)
        assertTrue(tracker.advance(2100).isEmpty())
    }

    @Test fun stalledServerCannotLeaveFramesForever() {
        val tracker = DetectionTracker()
        tracker.updateAt(0, detection(.1))
        assertTrue(tracker.advance(2999).single().visible)
        assertFalse(tracker.advance(3000).single().visible)
        assertTrue(tracker.advance(3500).isEmpty())
    }

    @Test fun differentComponentsAreNeverMerged() {
        val tracker = DetectionTracker()
        val first = tracker.updateAt(0, detection(.1, "C-1")).single()
        val second = tracker.updateAt(700, detection(.1, "C-2"))
        assertEquals(2, second.size)
        assertNotEquals(first.key, second.last().key)
        assertNotNull(second.first().missingSince)
    }

    @Test fun farAwayObjectDoesNotFlyAcrossPreview() {
        val tracker = DetectionTracker()
        val first = tracker.updateAt(0, detection(.1)).single()
        val newTrack = tracker.updateAt(700, detection(.75)).last()
        assertNotEquals(first.key, newTrack.key)
        assertEquals(.75, newTrack.box[0], .0001)
    }

    @Test fun removedKeysAreNotReused() {
        val tracker = DetectionTracker()
        val first = tracker.updateAt(0, detection(.1)).single()
        tracker.advance(3500)
        assertNotEquals(first.key, tracker.updateAt(4000, detection(.1)).single().key)
    }

    @Test fun invalidAndEmptyClippedBoxesAreIgnored() {
        val tracker = DetectionTracker()
        val valid = detection(.1)
        val invalid = listOf(valid.copy(bbox = listOf(.1)), valid.copy(bbox = listOf(Double.NaN, .2, .1, .1)),
            valid.copy(bbox = listOf(.2, .2, -.1, .1)), valid.copy(bbox = listOf(2.0, .2, .1, .1)))
        assertTrue(tracker.update(invalid, 0, 640, 480).isEmpty())
    }

    @Test fun changedPreviewDimensionsResetVisualTracking() {
        val tracker = DetectionTracker()
        val first = tracker.updateAt(0, detection(.1)).single()
        val second = tracker.update(listOf(detection(.1)), 700, 480, 640).last()
        assertNotEquals(first.key, second.key)
    }
}
