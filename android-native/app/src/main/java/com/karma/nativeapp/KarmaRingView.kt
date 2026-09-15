package com.karma.nativeapp

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View

/**
 * The product's thesis as a native widget: a conic ring that fills with earned karma and
 * walks the brand gradient (rose -> amber -> lime -> gold). Same data, same emotional
 * payload as the web KarmaRing, drawn with Canvas instead of SVG.
 */
class KarmaRingView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {

    var value: Int = 50
        set(v) {
            field = v.coerceIn(0, 100)
            invalidate()
        }

    private val trackPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        color = Color.parseColor("#26262E")
    }
    private val arcPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#FAFAF8")
        textAlign = Paint.Align.CENTER
        isFakeBoldText = true
    }
    private val bounds = RectF()

    private fun ringColor(v: Int): Int = when {
        v < 40 -> Color.parseColor("#BE123C")  // dormant
        v < 70 -> Color.parseColor("#B45309")  // building
        v < 85 -> Color.parseColor("#4D7C0F")  // trusted
        else -> Color.parseColor("#D4A017")    // proven
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val stroke = width * 0.12f
        trackPaint.strokeWidth = stroke
        arcPaint.strokeWidth = stroke
        arcPaint.color = ringColor(value)
        textPaint.textSize = width * 0.30f

        val half = stroke / 2
        bounds.set(half, half, width - half, height - half)

        canvas.drawArc(bounds, 0f, 360f, false, trackPaint)
        canvas.drawArc(bounds, -90f, value * 3.6f, false, arcPaint)

        val label = value.toString()
        val y = height / 2 - (textPaint.descent() + textPaint.ascent()) / 2
        canvas.drawText(label, width / 2f, y, textPaint)
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        // Keep it square.
        val d = MeasureSpec.getSize(widthMeasureSpec)
        super.onMeasure(
            MeasureSpec.makeMeasureSpec(d, MeasureSpec.EXACTLY),
            MeasureSpec.makeMeasureSpec(d, MeasureSpec.EXACTLY),
        )
    }
}
