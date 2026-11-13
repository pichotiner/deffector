package ru.kst.deffector

import org.junit.Assert.*
import org.junit.Test

class GeometryTest {
    @Test fun portraitPreviewAccountsForLetterbox() {
        val b = previewBox(listOf(.25, .25, .5, .5), 640, 480, 1080f, 1920f)
        assertEquals(270f, b.left, .01f)
        assertEquals(757.5f, b.top, .01f)
        assertEquals(810f, b.right, .01f)
        assertEquals(1162.5f, b.bottom, .01f)
    }
    @Test fun portraitImageMatchesPreview() {
        val b = previewBox(listOf(.1, .2, .3, .4), 480, 640, 480f, 640f)
        assertEquals(48f, b.left, .01f); assertEquals(128f, b.top, .01f)
        assertEquals(192f, b.right, .01f); assertEquals(384f, b.bottom, .01f)
    }
    @Test fun cropAddsFifteenPercentToEverySide() {
        assertArrayEquals(intArrayOf(170, 170, 260, 260), cropPixels(listOf(.2, .2, .2, .2), 1000, 1000))
    }
    @Test fun cropAtEdgeNeverLeavesImage() {
        assertArrayEquals(intArrayOf(0, 0, 1000, 800), cropPixels(listOf(0.0, 0.0, 1.0, 1.0), 1000, 800))
        val p = cropPixels(listOf(.99, .99, .2, .2), 100, 100)
        assertTrue(p[0] + p[2] <= 100 && p[1] + p[3] <= 100)
    }
    @Test(expected = IllegalArgumentException::class) fun invalidCoordinatesRejected() {
        normalizedBox(listOf(Double.NaN, .2, .2, .2))
    }
}
