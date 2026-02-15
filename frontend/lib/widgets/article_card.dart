import 'package:flutter/material.dart';
import 'package:glass_kit/glass_kit.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:lucide_icons/lucide_icons.dart';

class ArticleCard extends StatelessWidget {
  final Map<String, dynamic> article;

  const ArticleCard({super.key, required this.article});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.black, // Background for the "TikTok" feel
      child: Stack(
        children: [
          // Background Image or Gradient placeholder
          Container(
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [Colors.transparent, Colors.black87],
              ),
            ),
          ),
          
          // Content
          Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.end,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                GlassContainer.clearGlass(
                  height: 30,
                  width: 100,
                  borderRadius: BorderRadius.circular(15),
                  child: Center(
                    child: Text(
                      "Business", // Placeholder category
                      style: GoogleFonts.inter(
                        color: Colors.white, 
                        fontWeight: FontWeight.bold,
                        fontSize: 12
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                Text(
                  article['title'] ?? 'No Title',
                  style: GoogleFonts.outfit(
                    fontSize: 28,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                    height: 1.2,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  article['snippet'] ?? 'No Description',
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: GoogleFonts.inter(
                    fontSize: 16,
                    color: Colors.white70,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 100), // Space for bottom interactions
              ],
            ),
          ),

          // Right Side Actions
          Positioned(
            right: 16,
            bottom: 120,
            child: Column(
              children: [
                 _buildActionButton(LucideIcons.heart, "1.2k"),
                 const SizedBox(height: 24),
                 _buildActionButton(LucideIcons.messageCircle, "34"),
                 const SizedBox(height: 24),
                 _buildActionButton(LucideIcons.bookmark, "Save"),
                 const SizedBox(height: 24),
                 _buildActionButton(LucideIcons.share2, "Share"),
              ],
            ),
          )
        ],
      ),
    );
  }

  Widget _buildActionButton(IconData icon, String label) {
    return Column(
      children: [
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.1),
            shape: BoxShape.circle,
            border: Border.all(color: Colors.white.withOpacity(0.2)),
          ),
          child: Icon(icon, color: Colors.white, size: 28),
        ),
        const SizedBox(height: 4),
        Text(
          label, 
          style: GoogleFonts.inter(color: Colors.white, fontSize: 12),
        )
      ],
    );
  }
}
