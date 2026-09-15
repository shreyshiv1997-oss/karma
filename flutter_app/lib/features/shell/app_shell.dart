import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_theme.dart';
import '../../data/models/models.dart';
import '../../shared/widgets/primitives.dart';
import '../admin/admin_screen.dart';
import '../auth/session_controller.dart';
import '../booking/booking_screen.dart';
import '../feed/feed_screen.dart';
import '../gigs/gigs_screen.dart';
import '../karma/karma_screen.dart';
import '../profile/profile_screen.dart';

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _index = 0;
  int _feedRefresh = 0;
  int _gigRefresh = 0;
  int _karmaRefresh = 0;
  int _profileRefresh = 0;

  Future<void> _openBooking([String? category]) async {
    final bool? booked = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        fullscreenDialog: true,
        builder: (BuildContext context) => BookingScreen(
          preselectedCategory: category,
          onBooked: () {
            setState(() {
              _gigRefresh += 1;
              _profileRefresh += 1;
            });
          },
        ),
      ),
    );
    if ((booked ?? false) && mounted) {
      setState(() {
        _index = 1;
        _gigRefresh += 1;
      });
    }
  }

  Future<void> _create() async {
    final String? choice = await showModalBottomSheet<String>(
      context: context,
      useSafeArea: true,
      showDragHandle: true,
      builder: (BuildContext context) => const _CreateSheet(),
    );
    if (!mounted) return;
    if (choice == 'post') {
      final bool created = await showComposePostSheet(context);
      if (created && mounted) {
        setState(() {
          _index = 0;
          _feedRefresh += 1;
        });
      }
    }
    if (choice == 'gig') await _openBooking();
  }

  void _hireFromPost(PostModel post) => _openBooking(post.categoryName);

  void _openAdmin() {
    Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => const AdminScreen(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final User user = context.watch<SessionController>().user!;
    final List<Widget> screens = <Widget>[
      FeedScreen(
        refreshSignal: _feedRefresh,
        onHire: _hireFromPost,
      ),
      GigsScreen(
        refreshSignal: _gigRefresh,
        onPostGig: _openBooking,
      ),
      KarmaScreen(refreshSignal: _karmaRefresh),
      ProfileScreen(refreshSignal: _profileRefresh),
    ];
    const List<String> titles = <String>['KARMA', 'Gigs', 'Karma ledger', 'You'];

    return Scaffold(
      resizeToAvoidBottomInset: true,
      appBar: AppBar(
        titleSpacing: 18,
        title: Text(
          titles[_index],
          style: TextStyle(
            fontSize: _index == 0 ? 19 : 18,
            fontWeight: FontWeight.w800,
            letterSpacing: _index == 0 ? 1.2 : -0.2,
          ),
        ),
        actions: <Widget>[
          if (user.can('admin'))
            IconButton(
              tooltip: 'Open trust and safety console',
              onPressed: _openAdmin,
              icon: const Icon(Icons.admin_panel_settings_outlined),
            ),
          if (_index != 2)
            Semantics(
              button: true,
              label: 'Open Karma ledger. Current Karma ${user.karma}',
              child: InkWell(
                borderRadius: BorderRadius.circular(999),
                onTap: () => setState(() {
                  _index = 2;
                  _karmaRefresh += 1;
                }),
                child: Padding(
                  padding: const EdgeInsets.all(7),
                  child: KarmaRing(value: user.karma, size: 38),
                ),
              ),
            ),
          const SizedBox(width: 9),
        ],
      ),
      body: IndexedStack(index: _index, children: screens),
      floatingActionButtonLocation: FloatingActionButtonLocation.centerDocked,
      floatingActionButton: Semantics(
        label: 'Create a post or gig',
        button: true,
        child: FloatingActionButton(
          onPressed: _create,
          elevation: 0,
          highlightElevation: 0,
          backgroundColor: AppColors.violet,
          foregroundColor: Colors.white,
          shape: const CircleBorder(),
          child: const Icon(Icons.add_rounded, size: 31),
        ),
      ),
      bottomNavigationBar: BottomAppBar(
        elevation: 0,
        height: 72,
        padding: const EdgeInsets.symmetric(horizontal: 4),
        color: AppColors.surface,
        surfaceTintColor: Colors.transparent,
        shape: const CircularNotchedRectangle(),
        notchMargin: 7,
        child: Row(
          children: <Widget>[
            _NavButton(
              label: 'Home',
              icon: Icons.home_outlined,
              selectedIcon: Icons.home_rounded,
              selected: _index == 0,
              onTap: () => setState(() => _index = 0),
            ),
            _NavButton(
              label: 'Gigs',
              icon: Icons.work_outline_rounded,
              selectedIcon: Icons.work_rounded,
              selected: _index == 1,
              onTap: () => setState(() => _index = 1),
            ),
            const SizedBox(width: 66),
            _NavButton(
              label: 'Karma',
              icon: Icons.donut_large_outlined,
              selectedIcon: Icons.donut_large_rounded,
              selected: _index == 2,
              onTap: () => setState(() {
                _index = 2;
                _karmaRefresh += 1;
              }),
            ),
            _NavButton(
              label: 'You',
              icon: Icons.person_outline_rounded,
              selectedIcon: Icons.person_rounded,
              selected: _index == 3,
              onTap: () => setState(() => _index = 3),
            ),
          ],
        ),
      ),
    );
  }
}

class _NavButton extends StatelessWidget {
  const _NavButton({
    required this.label,
    required this.icon,
    required this.selectedIcon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final IconData selectedIcon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Semantics(
          selected: selected,
          button: true,
          label: label,
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: onTap,
            child: SizedBox(
              height: 60,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: <Widget>[
                  AnimatedContainer(
                    duration: AppTheme.quick,
                    width: 40,
                    height: 28,
                    decoration: BoxDecoration(
                      color: selected ? AppColors.paleViolet : Colors.transparent,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Icon(
                      selected ? selectedIcon : icon,
                      color: selected ? AppColors.violetInk : AppColors.textMuted,
                      size: 22,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    label,
                    style: TextStyle(
                      color: selected ? AppColors.violetInk : AppColors.textMuted,
                      fontSize: 11,
                      fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
}

class _CreateSheet extends StatelessWidget {
  const _CreateSheet();

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text('What are you here to do?', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 5),
            const Text(
              'Expression and work begin at the same door.',
              style: TextStyle(color: AppColors.textMuted),
            ),
            const SizedBox(height: 16),
            Row(
              children: <Widget>[
                Expanded(
                  child: _CreateChoice(
                    icon: Icons.edit_square,
                    color: AppColors.violet,
                    title: 'Share',
                    detail: 'Post an update',
                    onTap: () => Navigator.pop(context, 'post'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _CreateChoice(
                    icon: Icons.handyman_outlined,
                    color: AppColors.lime,
                    title: 'Post a gig',
                    detail: 'Find trusted help',
                    onTap: () => Navigator.pop(context, 'gig'),
                  ),
                ),
              ],
            ),
          ],
        ),
      );
}

class _CreateChoice extends StatelessWidget {
  const _CreateChoice({
    required this.icon,
    required this.color,
    required this.title,
    required this.detail,
    required this.onTap,
  });

  final IconData icon;
  final Color color;
  final String title;
  final String detail;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
        color: AppColors.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: AppColors.lineStrong),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 18),
            child: Column(
              children: <Widget>[
                Container(
                  width: 46,
                  height: 46,
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.1),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(icon, color: color),
                ),
                const SizedBox(height: 10),
                Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
                const SizedBox(height: 2),
                Text(detail, style: const TextStyle(color: AppColors.textMuted, fontSize: 12)),
              ],
            ),
          ),
        ),
      );
}
