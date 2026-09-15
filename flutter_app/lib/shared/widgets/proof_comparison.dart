import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/theme/app_theme.dart';

/// An accessible before/after wipe for paid-gig evidence.
class ProofComparison extends StatefulWidget {
  const ProofComparison({
    required this.beforeUrl,
    required this.afterUrl,
    super.key,
    this.height = 250,
  });

  final String beforeUrl;
  final String afterUrl;
  final double height;

  @override
  State<ProofComparison> createState() => _ProofComparisonState();
}

class _ProofComparisonState extends State<ProofComparison> {
  double _position = 0.5;

  void _set(double value) {
    setState(() => _position = value.clamp(0.0, 1.0).toDouble());
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final double width = constraints.maxWidth;
          return Semantics(
            label: 'Compare work before and after',
            value: '${(_position * 100).round()} percent before, '
                '${((1 - _position) * 100).round()} percent after',
            increasedValue: 'Show more before',
            decreasedValue: 'Show more after',
            onIncrease: () => _set(_position + 0.1),
            onDecrease: () => _set(_position - 0.1),
            slider: true,
            child: Focus(
              onKeyEvent: (FocusNode node, KeyEvent event) {
                if (event is! KeyDownEvent) return KeyEventResult.ignored;
                if (event.logicalKey == LogicalKeyboardKey.arrowLeft) {
                  _set(_position - 0.1);
                  return KeyEventResult.handled;
                }
                if (event.logicalKey == LogicalKeyboardKey.arrowRight) {
                  _set(_position + 0.1);
                  return KeyEventResult.handled;
                }
                return KeyEventResult.ignored;
              },
              child: GestureDetector(
                onTapDown: (TapDownDetails details) =>
                    _set(details.localPosition.dx / width),
                onHorizontalDragUpdate: (DragUpdateDetails details) =>
                    _set(_position + details.delta.dx / width),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(AppTheme.cardRadius),
                  child: SizedBox(
                    width: width,
                    height: widget.height,
                    child: Stack(
                      fit: StackFit.expand,
                      children: <Widget>[
                        _ProofImage(url: widget.afterUrl, label: 'After'),
                        // StackFit.expand gives non-positioned children tight
                        // constraints, which makes Align.widthFactor ineffective.
                        // Give the before layer an explicit viewport and let the
                        // full-width image overflow behind that clip instead.
                        Positioned(
                          left: 0,
                          top: 0,
                          bottom: 0,
                          width: width * _position,
                          child: ClipRect(
                            child: OverflowBox(
                              alignment: Alignment.centerLeft,
                              minWidth: width,
                              maxWidth: width,
                              minHeight: widget.height,
                              maxHeight: widget.height,
                              child: _ProofImage(
                                url: widget.beforeUrl,
                                label: 'Before',
                              ),
                            ),
                          ),
                        ),
                        Positioned(
                          left: width * _position - 1,
                          top: 0,
                          bottom: 0,
                          child: Container(width: 2, color: Colors.white),
                        ),
                        Positioned(
                          left: width * _position - 19,
                          top: widget.height / 2 - 19,
                          child: Container(
                            width: 38,
                            height: 38,
                            decoration: BoxDecoration(
                              color: Colors.white,
                              shape: BoxShape.circle,
                              border: Border.all(color: AppColors.lineStrong),
                            ),
                            child: const Icon(
                              Icons.compare_arrows_rounded,
                              size: 21,
                              color: AppColors.textMuted,
                            ),
                          ),
                        ),
                        const Positioned(
                          left: 10,
                          bottom: 10,
                          child: _ImageLabel('Before'),
                        ),
                        const Positioned(
                          right: 10,
                          bottom: 10,
                          child: _ImageLabel('After'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          );
        },
      );
}

class _ProofImage extends StatelessWidget {
  const _ProofImage({required this.url, required this.label});

  final String url;
  final String label;

  @override
  Widget build(BuildContext context) => CachedNetworkImage(
        imageUrl: url,
        fit: BoxFit.cover,
        fadeInDuration: AppTheme.enter,
        placeholder: (BuildContext context, String url) =>
            const ColoredBox(color: AppColors.surfaceMuted),
        errorWidget: (BuildContext context, String url, Object error) => ColoredBox(
          color: AppColors.surfaceMuted,
          child: Center(
            child: Text(
              '$label image unavailable',
              style: const TextStyle(color: AppColors.textMuted),
            ),
          ),
        ),
      );
}

class _ImageLabel extends StatelessWidget {
  const _ImageLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
        decoration: BoxDecoration(
          color: AppColors.ink.withValues(alpha: 0.76),
          borderRadius: BorderRadius.circular(999),
        ),
        child: Text(
          text.toUpperCase(),
          style: const TextStyle(
            color: Colors.white,
            fontSize: 10.5,
            fontWeight: FontWeight.w800,
            letterSpacing: 0.7,
          ),
        ),
      );
}
