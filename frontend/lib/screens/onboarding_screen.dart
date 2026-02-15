import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:glass_kit/glass_kit.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:lucide_icons/lucide_icons.dart';
import '../services/api_service.dart';

class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final ApiService _api = ApiService();
  static const String _demoUserId = 'demo-user';
  int _step = 0; // 0: Broad Category, 1: Specific Tags
  String? _selectedCategory;
  final Set<String> _selectedTags = {};
  bool _submitting = false;

  final Map<String, List<String>> _tagData = {
    'Technology': ['AI & Ethics', 'Gadgets', 'Programming', 'Startups', 'Cybersecurity'],
    'Business': ['Marketing', 'Finance', 'Leadership', 'Economy', 'Remote Work'],
    'Science': ['Space', 'Health', 'Biology', 'Environment', 'Physics'],
    'Culture': ['Movies', 'Music', 'History', 'Art', 'Gaming'],
  };

  Future<void> _nextStep() async {
    if (_step == 0 && _selectedCategory != null) {
      setState(() => _step = 1);
    } else if (_step == 1 && _selectedTags.isNotEmpty) {
      setState(() => _submitting = true);
      try {
        await _api.upsertUserProfile(
          userId: _demoUserId,
          category: _selectedCategory!,
          tags: _selectedTags.toList(),
        );
      } catch (_) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to save onboarding profile')),
        );
      } finally {
        if (mounted) {
          setState(() => _submitting = false);
        }
      }
      if (!mounted) return;
      Navigator.of(context).pushReplacementNamed('/home');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF0F172A), Color(0xFF1E293B), Color(0xFF334155)],
          ),
        ),
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Spacer(),
                Text(
                  _step == 0 ? "What are you\ninterested in?" : "Let's dig deeper.",
                  style: GoogleFonts.outfit(
                    fontSize: 48,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                    height: 1.1,
                  ),
                ).animate().fadeIn(duration: 600.ms).slideY(begin: 0.3, end: 0),
                const SizedBox(height: 16),
                Text(
                  _step == 0
                      ? "Pick a broad category to start."
                      : "Select specifically what you want to hear about $_selectedCategory.",
                  style: GoogleFonts.inter(
                    fontSize: 18,
                    color: Colors.white70,
                  ),
                ).animate().fadeIn(delay: 200.ms).slideY(begin: 0.3, end: 0),
                const SizedBox(height: 48),
                Expanded(
                  flex: 3,
                  child: _step == 0 ? _buildCategoryGrid() : _buildTagCloud(),
                ),
                const Spacer(),
                Center(
                  child: GlassContainer.clearGlass(
                    height: 60,
                    width: 200,
                    borderRadius: BorderRadius.circular(30),
                    blur: 10,
                    borderWidth: 0,
                    elevation: 5,
                    child: InkWell(
                      onTap: _submitting ? null : _nextStep,
                      borderRadius: BorderRadius.circular(30),
                      child: Center(
                        child: Text(
                          _submitting ? "Saving..." : "Continue",
                          style: GoogleFonts.inter(
                            fontSize: 18,
                            fontWeight: FontWeight.w600,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                  ).animate(target: (_step == 0 && _selectedCategory != null) || (_step == 1 && _selectedTags.isNotEmpty) ? 1 : 0)
                   .fadeIn()
                   .scale(),
                ),
                const SizedBox(height: 32),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCategoryGrid() {
    return GridView.count(
      crossAxisCount: 2,
      mainAxisSpacing: 16,
      crossAxisSpacing: 16,
      childAspectRatio: 1.5,
      children: _tagData.keys.map((category) {
        final isSelected = _selectedCategory == category;
        return GestureDetector(
          onTap: () => setState(() => _selectedCategory = category),
          child: AnimatedContainer(
            duration: 200.ms,
            decoration: BoxDecoration(
              color: isSelected ? Theme.of(context).primaryColor : Colors.white.withOpacity(0.1),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(
                color: isSelected ? Colors.transparent : Colors.white.withOpacity(0.2),
              ),
            ),
            child: Center(
              child: Text(
                category,
                style: GoogleFonts.inter(
                  fontSize: 20,
                  fontWeight: FontWeight.w600,
                  color: isSelected ? Colors.white : Colors.white70,
                ),
              ),
            ),
          ),
        );
      }).toList(),
    ).animate().fadeIn(delay: 400.ms);
  }

  Widget _buildTagCloud() {
    final tags = _tagData[_selectedCategory] ?? [];
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: tags.map((tag) {
        final isSelected = _selectedTags.contains(tag);
        return GestureDetector(
          onTap: () {
            setState(() {
              if (isSelected) {
                _selectedTags.remove(tag);
              } else {
                _selectedTags.add(tag);
              }
            });
          },
          child: AnimatedContainer(
            duration: 200.ms,
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
            decoration: BoxDecoration(
              color: isSelected ? Theme.of(context).primaryColor : Colors.white.withOpacity(0.1),
              borderRadius: BorderRadius.circular(30),
              border: Border.all(
                color: isSelected ? Colors.transparent : Colors.white.withOpacity(0.2),
              ),
            ),
            child: Text(
              tag,
              style: GoogleFonts.inter(
                fontSize: 16,
                fontWeight: FontWeight.w500,
                color: isSelected ? Colors.white : Colors.white70,
              ),
            ),
          ),
        );
      }).toList(),
    ).animate().fadeIn(delay: 400.ms);
  }
}
