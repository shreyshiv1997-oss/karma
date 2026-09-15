import 'dart:math' as math;
import 'dart:ui' show FontFeature;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';

class ContentRail extends StatelessWidget {
  const ContentRail({required this.child, super.key, this.padding});

  final Widget child;
  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: AppTheme.contentMaxWidth),
          child: Padding(
            padding: padding ?? const EdgeInsets.fromLTRB(16, 12, 16, 112),
            child: child,
          ),
        ),
      );
}

class KarmaCard extends StatelessWidget {
  const KarmaCard({
    required this.child,
    super.key,
    this.padding = const EdgeInsets.all(18),
    this.color = AppColors.surface,
    this.onTap,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color color;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Material(
        color: color,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppTheme.cardRadius),
          side: const BorderSide(color: AppColors.line),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(padding: padding, child: child),
        ),
      );
}

class SectionLabel extends StatelessWidget {
  const SectionLabel(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Row(
        children: <Widget>[
          Expanded(
            child: Text(
              text.toUpperCase(),
              style: const TextStyle(
                color: AppColors.textMuted,
                fontSize: 12,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.8,
              ),
            ),
          ),
          if (trailing != null) trailing!,
        ],
      );
}

class UserAvatar extends StatelessWidget {
  const UserAvatar({
    required this.name,
    super.key,
    this.url,
    this.radius = 22,
  });

  final String name;
  final String? url;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final String initial = name.trim().isEmpty ? '?' : name.trim()[0].toUpperCase();
    final bool hasImage = url != null && url!.isNotEmpty;
    return Semantics(
      image: true,
      label: '$name profile photo',
      child: CircleAvatar(
        radius: radius,
        backgroundColor: AppColors.surfaceMuted,
        foregroundImage: hasImage ? CachedNetworkImageProvider(url!) : null,
        onForegroundImageError: hasImage ? (_, __) {} : null,
        child: Text(
          initial,
          style: TextStyle(
            color: AppColors.violetInk,
            fontWeight: FontWeight.w800,
            fontSize: radius * 0.72,
          ),
        ),
      ),
    );
  }
}

class TierBadge extends StatelessWidget {
  const TierBadge({required this.tier, super.key});

  final String tier;

  @override
  Widget build(BuildContext context) {
    final (Color foreground, Color background) = switch (tier) {
      'gold' => (AppColors.gold, AppColors.paleGold),
      'silver' => (const Color(0xFF475569), const Color(0xFFF1F5F9)),
      'bronze' => (const Color(0xFF7C5C3D), const Color(0xFFFBF3EA)),
      _ => (AppColors.textMuted, AppColors.surfaceMuted),
    };
    return Semantics(
      label: '$tier verification tier',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
        decoration: BoxDecoration(
          color: background,
          borderRadius: BorderRadius.circular(999),
        ),
        child: Text(
          '${tier == 'none' ? '' : '◆ '}${_title(tier)}',
          style: TextStyle(
            color: foreground,
            fontWeight: FontWeight.w700,
            fontSize: 11.5,
          ),
        ),
      ),
    );
  }

  static String _title(String value) =>
      value.isEmpty ? value : '${value[0].toUpperCase()}${value.substring(1)}';
}

Color karmaHue(num value) {
  if (value < 35) return AppColors.rose;
  if (value < 60) return AppColors.gold;
  if (value < 80) return AppColors.lime;
  return const Color(0xFF92400E);
}

String karmaBand(num value) {
  if (value < 35) return 'Dormant';
  if (value < 60) return 'Building';
  if (value < 80) return 'Trusted';
  return 'Proven';
}

class KarmaRing extends StatelessWidget {
  const KarmaRing({
    required this.value,
    super.key,
    this.size = 52,
    this.showValue = true,
  });

  final num value;
  final double size;
  final bool showValue;

  @override
  Widget build(BuildContext context) => Semantics(
        label: 'Karma ${value.round()} out of 100, ${karmaBand(value)}',
        readOnly: true,
        child: TweenAnimationBuilder<double>(
          duration: AppTheme.enter,
          curve: Curves.easeOutCubic,
          tween: Tween<double>(begin: 0, end: value.clamp(0, 100).toDouble()),
          builder: (BuildContext context, double animated, Widget? child) {
            return SizedBox.square(
              dimension: size,
              child: CustomPaint(
                painter: _KarmaRingPainter(animated / 100),
                child: showValue
                    ? Center(
                        child: ExcludeSemantics(
                          child: Text(
                            value.round().toString(),
                            style: TextStyle(
                              fontSize: size * 0.27,
                              fontWeight: FontWeight.w800,
                              fontFeatures: const <FontFeature>[
                                FontFeature.tabularFigures(),
                              ],
                            ),
                          ),
                        ),
                      )
                    : null,
              ),
            );
          },
        ),
      );
}

class _KarmaRingPainter extends CustomPainter {
  const _KarmaRingPainter(this.progress);

  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final double stroke = math.max(3.0, size.shortestSide * 0.085);
    final Rect rect = Offset.zero & size;
    final Rect arcRect = rect.deflate(stroke / 2);
    final Paint track = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..color = AppColors.line
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(arcRect, -math.pi / 2, math.pi * 2, false, track);

    if (progress <= 0) return;
    final Paint active = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round
      ..shader = const SweepGradient(
        transform: GradientRotation(-math.pi / 2),
        colors: <Color>[
          AppColors.rose,
          AppColors.gold,
          AppColors.lime,
          Color(0xFF92400E),
          AppColors.rose,
        ],
      ).createShader(rect);
    canvas.drawArc(
      arcRect,
      -math.pi / 2,
      math.pi * 2 * progress.clamp(0.0, 1.0).toDouble(),
      false,
      active,
    );
  }

  @override
  bool shouldRepaint(_KarmaRingPainter oldDelegate) => oldDelegate.progress != progress;
}

class ErrorPanel extends StatelessWidget {
  const ErrorPanel({
    required this.message,
    required this.onRetry,
    super.key,
  });

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => KarmaCard(
        color: const Color(0xFFFFF5F7),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const Icon(Icons.cloud_off_outlined, color: AppColors.rose, size: 30),
            const SizedBox(height: 10),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 10),
            TextButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Try again'),
            ),
          ],
        ),
      );
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    required this.icon,
    required this.title,
    required this.message,
    super.key,
    this.action,
  });

  final IconData icon;
  final String title;
  final String message;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 48),
        child: Column(
          children: <Widget>[
            Icon(icon, size: 42, color: AppColors.textFaint),
            const SizedBox(height: 14),
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textMuted),
            ),
            if (action != null) ...<Widget>[
              const SizedBox(height: 16),
              action!,
            ],
          ],
        ),
      );
}

class LoadingCards extends StatelessWidget {
  const LoadingCards({super.key, this.count = 2});

  final int count;

  @override
  Widget build(BuildContext context) => Column(
        children: List<Widget>.generate(count, (int index) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: KarmaCard(
              child: SizedBox(
                height: 118,
                child: Row(
                  children: <Widget>[
                    const _Skeleton(width: 48, height: 48, circle: true),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: const <Widget>[
                          _Skeleton(width: 160, height: 14),
                          SizedBox(height: 10),
                          _Skeleton(width: 230, height: 12),
                          SizedBox(height: 8),
                          _Skeleton(width: 120, height: 12),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }),
      );
}

class _Skeleton extends StatelessWidget {
  const _Skeleton({required this.width, required this.height, this.circle = false});

  final double width;
  final double height;
  final bool circle;

  @override
  Widget build(BuildContext context) => Container(
        width: width,
        height: height,
        decoration: BoxDecoration(
          color: AppColors.surfaceMuted,
          borderRadius: BorderRadius.circular(circle ? 999 : 6),
        ),
      );
}

String errorMessage(Object error) {
  final String value = error.toString();
  return value.startsWith('Exception: ') ? value.substring(11) : value;
}
